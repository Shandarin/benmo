import {
  Aws,
  CfnOutput,
  CfnParameter,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  aws_applicationautoscaling as appscaling,
  aws_certificatemanager as acm,
  aws_cloudwatch as cloudwatch,
  aws_ec2 as ec2,
  aws_ecs as ecs,
  aws_elasticloadbalancingv2 as elbv2,
  aws_iam as iam,
  aws_logs as logs,
  aws_rds as rds,
  aws_s3 as s3,
  aws_scheduler as scheduler,
  aws_servicediscovery as servicediscovery,
  aws_secretsmanager as secretsmanager,
  aws_sqs as sqs,
  aws_stepfunctions as sfn,
  aws_stepfunctions_tasks as tasks,
  aws_wafv2 as wafv2,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';

interface QueueWithDlq {
  readonly queue: sqs.Queue;
  readonly dlq: sqs.Queue;
}

interface WorkerRuntime {
  readonly taskDefinition: ecs.FargateTaskDefinition;
  readonly container: ecs.ContainerDefinition;
  readonly service: ecs.FargateService;
}

export class BenmoPlatformStack extends Stack {
  public constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const certificateArn = new CfnParameter(this, 'CertificateArn', {
      type: 'String',
      description: 'ACM certificate ARN for the public API HTTPS listener.',
    });
    const apiImageUri = new CfnParameter(this, 'ApiImageUri', {
      type: 'String',
      description: 'Immutable ECR image URI for the Benmo API.',
    });
    const workerImageUri = new CfnParameter(this, 'WorkerImageUri', {
      type: 'String',
      description: 'Immutable ECR image URI shared by all Benmo workers.',
    });
    const frontendImageUri = new CfnParameter(this, 'FrontendImageUri', {
      type: 'String',
      description: 'Immutable ECR image URI for the Benmo Next.js frontend.',
    });
    const siteUrl = new CfnParameter(this, 'SiteUrl', {
      type: 'String',
      description: 'Canonical HTTPS origin for the public Benmo website.',
    });
    const corsOrigins = new CfnParameter(this, 'CorsOrigins', {
      type: 'String',
      default: '[]',
      description: 'JSON array consumed by BENMO_CORS_ORIGINS.',
    });
    const secUserAgent = new CfnParameter(this, 'SecUserAgent', {
      type: 'String',
      default: 'Benmo/0.1 ops@example.invalid',
      description: 'Contactable SEC User-Agent. Override the placeholder before live collection.',
    });
    const stage = 'production';
    const namePrefix = `benmo-${stage}`;
    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.40.0.0/16'),
      maxAzs: 2,
      natGateways: 0,
      restrictDefaultSecurityGroup: true,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        {
          name: 'application',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
          reserved: true,
        },
        { name: 'database', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    const flowLogGroup = new logs.LogGroup(this, 'VpcFlowLogGroup', {
      logGroupName: `/benmo/${stage}/vpc-flow`,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const flowLogRole = new iam.Role(this, 'VpcFlowLogRole', {
      assumedBy: new iam.ServicePrincipal('vpc-flow-logs.amazonaws.com'),
    });
    new ec2.FlowLog(this, 'VpcFlowLog', {
      resourceType: ec2.FlowLogResourceType.fromVpc(vpc),
      destination: ec2.FlowLogDestination.toCloudWatchLogs(flowLogGroup, flowLogRole),
      trafficType: ec2.FlowLogTrafficType.REJECT,
    });

    const artifacts = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `${namePrefix}-artifacts-${Aws.ACCOUNT_ID}-${Aws.REGION}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      removalPolicy: RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      lifecycleRules: [
        {
          id: 'abort-incomplete-uploads',
          abortIncompleteMultipartUploadAfter: Duration.days(7),
          noncurrentVersionExpiration: Duration.days(365),
        },
      ],
    });

    const analysisQueue = this.queueWithDlq('AnalysisRequested', namePrefix, Duration.minutes(15));
    const sourceFetchQueue = this.queueWithDlq('SourceFetch', namePrefix, Duration.minutes(5));
    const filingQueue = this.queueWithDlq('FilingProcessing', namePrefix, Duration.minutes(15));
    const verificationQueue = this.queueWithDlq(
      'IndicatorVerification',
      namePrefix,
      Duration.minutes(5),
    );
    const manualReviewQueue = this.queueWithDlq('ManualReview', namePrefix, Duration.minutes(2));
    const ingestionQueue = this.queueWithDlq('EventIngestion', namePrefix, Duration.minutes(2));
    const queueSet = [
      analysisQueue,
      sourceFetchQueue,
      filingQueue,
      verificationQueue,
      manualReviewQueue,
      ingestionQueue,
    ];

    const databaseSecurityGroup = new ec2.SecurityGroup(this, 'DatabaseSecurityGroup', {
      vpc,
      allowAllOutbound: false,
      description: 'RDS accepts PostgreSQL only from Benmo ECS tasks.',
    });
    const database = new rds.DatabaseInstance(this, 'Database', {
      databaseName: 'benmo',
      credentials: rds.Credentials.fromGeneratedSecret('benmo_app', {
        secretName: `${namePrefix}/database`,
      }),
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      allocatedStorage: 20,
      maxAllocatedStorage: 100,
      storageEncrypted: true,
      storageType: rds.StorageType.GP3,
      multiAz: false,
      autoMinorVersionUpgrade: true,
      backupRetention: Duration.days(7),
      copyTagsToSnapshot: true,
      deletionProtection: true,
      enablePerformanceInsights: false,
      cloudwatchLogsExports: ['postgresql', 'upgrade'],
      cloudwatchLogsRetention: logs.RetentionDays.ONE_MONTH,
      publiclyAccessible: false,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [databaseSecurityGroup],
      removalPolicy: RemovalPolicy.SNAPSHOT,
    });

    const adminApiKey = new secretsmanager.Secret(this, 'AdminApiKey', {
      secretName: `${namePrefix}/admin-api-key`,
      description: 'Admin API key generated by CloudFormation.',
      generateSecretString: { passwordLength: 48, excludePunctuation: true },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const internalToken = new secretsmanager.Secret(this, 'InternalToken', {
      secretName: `${namePrefix}/backend-internal-token`,
      description: 'Shared token for authenticated worker callbacks.',
      generateSecretString: { passwordLength: 48, excludePunctuation: true },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const providerCredentials = secretsmanager.Secret.fromSecretNameV2(
      this,
      'ProviderCredentials',
      'benmo-production/provider-credentials',
    );

    const cluster = new ecs.Cluster(this, 'Cluster', {
      clusterName: `${namePrefix}-cluster`,
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
      enableFargateCapacityProviders: true,
      vpc,
    });
    cluster.addDefaultCloudMapNamespace({
      name: 'benmo.local',
      vpc,
    });

    const albSecurityGroup = new ec2.SecurityGroup(this, 'AlbSecurityGroup', {
      vpc,
      allowAllOutbound: false,
      description: 'Public HTTPS ingress to the Benmo API load balancer.',
    });
    albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP redirect');
    albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');

    const apiSecurityGroup = new ec2.SecurityGroup(this, 'ApiSecurityGroup', {
      vpc,
      allowAllOutbound: true,
      description: 'API tasks receive traffic from the ALB and workers only.',
    });
    const workerSecurityGroup = new ec2.SecurityGroup(this, 'WorkerSecurityGroup', {
      vpc,
      allowAllOutbound: true,
      description: 'Worker tasks use outbound provider, S3, SQS and database connections.',
    });
    const frontendSecurityGroup = new ec2.SecurityGroup(this, 'FrontendSecurityGroup', {
      vpc,
      allowAllOutbound: true,
      description: 'Frontend tasks receive ALB traffic and call the internal API.',
    });
    apiSecurityGroup.addIngressRule(albSecurityGroup, ec2.Port.tcp(8000), 'ALB to API');
    apiSecurityGroup.addIngressRule(workerSecurityGroup, ec2.Port.tcp(8000), 'Worker callbacks');
    apiSecurityGroup.addIngressRule(
      frontendSecurityGroup,
      ec2.Port.tcp(8000),
      'Frontend server rendering to API',
    );
    frontendSecurityGroup.addIngressRule(
      albSecurityGroup,
      ec2.Port.tcp(3000),
      'ALB to frontend',
    );
    databaseSecurityGroup.addIngressRule(apiSecurityGroup, ec2.Port.tcp(5432), 'API to PostgreSQL');
    databaseSecurityGroup.addIngressRule(workerSecurityGroup, ec2.Port.tcp(5432), 'Worker to PostgreSQL');

    const apiTaskDefinition = new ecs.FargateTaskDefinition(this, 'ApiTaskDefinition', {
      family: `${namePrefix}-api`,
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    const apiLogGroup = new logs.LogGroup(this, 'ApiLogGroup', {
      logGroupName: `/benmo/${stage}/api`,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const apiContainer = apiTaskDefinition.addContainer('api', {
      image: ecs.ContainerImage.fromRegistry(apiImageUri.valueAsString),
      logging: ecs.LogDrivers.awsLogs({ logGroup: apiLogGroup, streamPrefix: 'api' }),
      environment: {
        BENMO_ENVIRONMENT: 'production',
        BENMO_QUEUE_BACKEND: 'sqs',
        BENMO_AWS_REGION: Aws.REGION,
        BENMO_SQS_ANALYSIS_QUEUE_URL: analysisQueue.queue.queueUrl,
        BENMO_DATABASE_HOST: database.instanceEndpoint.hostname,
        BENMO_DATABASE_PORT: database.instanceEndpoint.port.toString(),
        BENMO_DATABASE_NAME: 'benmo',
        BENMO_CORS_ORIGINS: corsOrigins.valueAsString,
        BENMO_LOG_LEVEL: 'INFO',
      },
      secrets: {
        BENMO_ADMIN_API_KEY: ecs.Secret.fromSecretsManager(adminApiKey),
        BENMO_BACKEND_INTERNAL_TOKEN: ecs.Secret.fromSecretsManager(internalToken),
        BENMO_DATABASE_USER: ecs.Secret.fromSecretsManager(database.secret!, 'username'),
        BENMO_DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, 'password'),
      },
      healthCheck: {
        command: [
          'CMD-SHELL',
          "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=3)\" || exit 1",
        ],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(30),
      },
    });
    apiContainer.addPortMappings({ containerPort: 8000, protocol: ecs.Protocol.TCP });
    analysisQueue.queue.grantSendMessages(apiTaskDefinition.taskRole);
    ingestionQueue.queue.grantSendMessages(apiTaskDefinition.taskRole);

    const apiService = new ecs.FargateService(this, 'ApiService', {
      serviceName: `${namePrefix}-api`,
      cluster,
      taskDefinition: apiTaskDefinition,
      desiredCount: 1,
      assignPublicIp: true,
      circuitBreaker: { rollback: true },
      enableECSManagedTags: true,
      propagateTags: ecs.PropagatedTagSource.SERVICE,
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      securityGroups: [apiSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      cloudMapOptions: {
        name: 'api',
        dnsRecordType: servicediscovery.DnsRecordType.A,
        dnsTtl: Duration.seconds(30),
      },
    });
    apiService
      .autoScaleTaskCount({ minCapacity: 1, maxCapacity: 10 })
      .scaleOnCpuUtilization('ApiCpuScaling', {
        targetUtilizationPercent: 60,
        scaleInCooldown: Duration.minutes(5),
        scaleOutCooldown: Duration.minutes(1),
      });

    const frontendTaskDefinition = new ecs.FargateTaskDefinition(
      this,
      'FrontendTaskDefinition',
      {
        family: `${namePrefix}-frontend`,
        cpu: 512,
        memoryLimitMiB: 1024,
        runtimePlatform: {
          cpuArchitecture: ecs.CpuArchitecture.X86_64,
          operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        },
      },
    );
    const frontendLogGroup = new logs.LogGroup(this, 'FrontendLogGroup', {
      logGroupName: `/benmo/${stage}/frontend`,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const frontendContainer = frontendTaskDefinition.addContainer('frontend', {
      image: ecs.ContainerImage.fromRegistry(frontendImageUri.valueAsString),
      logging: ecs.LogDrivers.awsLogs({
        logGroup: frontendLogGroup,
        streamPrefix: 'frontend',
      }),
      environment: {
        BENMO_API_BASE_URL: 'http://api.benmo.local:8000',
        SITE_URL: siteUrl.valueAsString,
        PORT: '3000',
        HOSTNAME: '0.0.0.0',
        NODE_ENV: 'production',
      },
      healthCheck: {
        command: [
          'CMD-SHELL',
          "wget --quiet --spider http://localhost:3000/healthz || exit 1",
        ],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(30),
      },
    });
    frontendContainer.addPortMappings({
      containerPort: 3000,
      protocol: ecs.Protocol.TCP,
    });
    const frontendService = new ecs.FargateService(this, 'FrontendService', {
      serviceName: `${namePrefix}-frontend`,
      cluster,
      taskDefinition: frontendTaskDefinition,
      desiredCount: 1,
      assignPublicIp: true,
      circuitBreaker: { rollback: true },
      enableECSManagedTags: true,
      propagateTags: ecs.PropagatedTagSource.SERVICE,
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      securityGroups: [frontendSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });
    frontendService
      .autoScaleTaskCount({ minCapacity: 1, maxCapacity: 5 })
      .scaleOnCpuUtilization('FrontendCpuScaling', {
        targetUtilizationPercent: 60,
        scaleInCooldown: Duration.minutes(5),
        scaleOutCooldown: Duration.minutes(1),
      });

    const loadBalancer = new elbv2.ApplicationLoadBalancer(this, 'LoadBalancer', {
      loadBalancerName: `${namePrefix}-api`,
      internetFacing: true,
      ipAddressType: elbv2.IpAddressType.IPV4,
      securityGroup: albSecurityGroup,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });
    loadBalancer.setAttribute('deletion_protection.enabled', 'true');
    loadBalancer.setAttribute('idle_timeout.timeout_seconds', '120');
    loadBalancer.logAccessLogs(artifacts, 'access-logs/alb');
    albSecurityGroup.addEgressRule(apiSecurityGroup, ec2.Port.tcp(8000), 'ALB to API tasks');
    albSecurityGroup.addEgressRule(
      frontendSecurityGroup,
      ec2.Port.tcp(3000),
      'ALB to frontend tasks',
    );

    loadBalancer.addListener('HttpListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.redirect({
        protocol: 'HTTPS',
        port: '443',
        permanent: true,
      }),
    });
    const certificate = acm.Certificate.fromCertificateArn(
      this,
      'ApiCertificate',
      certificateArn.valueAsString,
    );
    const httpsListener = loadBalancer.addListener('HttpsListener', {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [certificate],
      sslPolicy: elbv2.SslPolicy.RECOMMENDED_TLS,
    });
    httpsListener.addTargets('FrontendTargets', {
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [frontendService],
      deregistrationDelay: Duration.seconds(30),
      healthCheck: {
        path: '/healthz',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
      },
    });
    httpsListener.addTargets('ApiTargets', {
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [apiService],
      priority: 10,
      conditions: [
        elbv2.ListenerCondition.pathPatterns(['/v1/*', '/health/*']),
      ],
      deregistrationDelay: Duration.seconds(30),
      healthCheck: {
        path: '/health/ready',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
      },
    });

    const webAcl = new wafv2.CfnWebACL(this, 'WebAcl', {
      name: `${namePrefix}-api`,
      scope: 'REGIONAL',
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: `${namePrefix}-api-waf`,
        sampledRequestsEnabled: true,
      },
      rules: [
        {
          name: 'AWSManagedCommonRules',
          priority: 0,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              name: 'AWSManagedRulesCommonRuleSet',
              vendorName: 'AWS',
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${namePrefix}-waf-common`,
            sampledRequestsEnabled: true,
          },
        },
        {
          name: 'AWSManagedKnownBadInputs',
          priority: 1,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              name: 'AWSManagedRulesKnownBadInputsRuleSet',
              vendorName: 'AWS',
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${namePrefix}-waf-bad-inputs`,
            sampledRequestsEnabled: true,
          },
        },
        {
          name: 'AnalysisSubmissionRateLimit',
          priority: 2,
          action: { block: {} },
          statement: {
            rateBasedStatement: {
              aggregateKeyType: 'IP',
              evaluationWindowSec: 300,
              limit: 10,
              scopeDownStatement: {
                andStatement: {
                  statements: [
                    {
                      byteMatchStatement: {
                        fieldToMatch: { method: {} },
                        positionalConstraint: 'EXACTLY',
                        searchString: 'POST',
                        textTransformations: [{ priority: 0, type: 'NONE' }],
                      },
                    },
                    {
                      byteMatchStatement: {
                        fieldToMatch: { uriPath: {} },
                        positionalConstraint: 'EXACTLY',
                        searchString: '/v1/analyses',
                        textTransformations: [{ priority: 0, type: 'NONE' }],
                      },
                    },
                  ],
                },
              },
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${namePrefix}-waf-analysis-submit-rate`,
            sampledRequestsEnabled: true,
          },
        },
        {
          name: 'IpRateLimit',
          priority: 3,
          action: { block: {} },
          statement: {
            rateBasedStatement: {
              aggregateKeyType: 'IP',
              evaluationWindowSec: 300,
              limit: 2000,
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${namePrefix}-waf-rate-limit`,
            sampledRequestsEnabled: true,
          },
        },
      ],
    });
    new wafv2.CfnWebACLAssociation(this, 'WebAclAssociation', {
      resourceArn: loadBalancer.loadBalancerArn,
      webAclArn: webAcl.attrArn,
    });

    const commonWorkerEnvironment: Record<string, string> = {
      BENMO_ENV: 'production',
      BENMO_PROVIDER_MODE: 'live',
      BENMO_BACKEND_BASE_URL: 'http://api.benmo.local:8000',
      BENMO_OBJECT_STORE: 's3',
      BENMO_S3_BUCKET: artifacts.bucketName,
      BENMO_S3_PREFIX: 'benmo',
      BENMO_RESEARCH_QUEUE_URL: analysisQueue.queue.queueUrl,
      BENMO_DOCUMENT_QUEUE_URL: filingQueue.queue.queueUrl,
      BENMO_DOCUMENT_QUEUE_URLS: `${sourceFetchQueue.queue.queueUrl},${filingQueue.queue.queueUrl}`,
      BENMO_VERIFICATION_QUEUE_URL: verificationQueue.queue.queueUrl,
      BENMO_MANUAL_REVIEW_QUEUE_URL: manualReviewQueue.queue.queueUrl,
      AWS_REGION: Aws.REGION,
      BENMO_AWS_REGION: Aws.REGION,
      BENMO_OPENAI_MODEL: 'gpt-5.6',
      BENMO_SEC_USER_AGENT: secUserAgent.valueAsString,
    };
    const commonWorkerSecrets: Record<string, ecs.Secret> = {
      BENMO_BACKEND_INTERNAL_TOKEN: ecs.Secret.fromSecretsManager(internalToken),
      BENMO_OPENAI_API_KEY: ecs.Secret.fromSecretsManager(providerCredentials, 'OPENAI_API_KEY'),
      BENMO_FINNHUB_API_KEY: ecs.Secret.fromSecretsManager(
        providerCredentials,
        'FINNHUB_API_KEY',
      ),
      BENMO_ALPHA_VANTAGE_API_KEY: ecs.Secret.fromSecretsManager(
        providerCredentials,
        'ALPHA_VANTAGE_API_KEY',
      ),
      BENMO_FRED_API_KEY: ecs.Secret.fromSecretsManager(providerCredentials, 'FRED_API_KEY'),
      BENMO_BLS_API_KEY: ecs.Secret.fromSecretsManager(providerCredentials, 'BLS_API_KEY'),
      BENMO_EIA_API_KEY: ecs.Secret.fromSecretsManager(providerCredentials, 'EIA_API_KEY'),
      BENMO_BEA_API_KEY: ecs.Secret.fromSecretsManager(providerCredentials, 'BEA_API_KEY'),
    };

    const researchWorker = this.createWorkerRuntime({
      id: 'ResearchWorker',
      serviceName: `${namePrefix}-research-worker`,
      workerName: 'research',
      desiredCount: 0,
      cluster,
      imageUri: workerImageUri.valueAsString,
      securityGroup: workerSecurityGroup,
      environment: commonWorkerEnvironment,
      secrets: commonWorkerSecrets,
      stage,
    });
    const documentWorker = this.createWorkerRuntime({
      id: 'DocumentWorker',
      serviceName: `${namePrefix}-document-worker`,
      workerName: 'document',
      desiredCount: 0,
      cluster,
      imageUri: workerImageUri.valueAsString,
      securityGroup: workerSecurityGroup,
      environment: commonWorkerEnvironment,
      secrets: commonWorkerSecrets,
      stage,
    });
    const verificationWorker = this.createWorkerRuntime({
      id: 'VerificationWorker',
      serviceName: `${namePrefix}-verification-worker`,
      workerName: 'verification',
      desiredCount: 0,
      cluster,
      imageUri: workerImageUri.valueAsString,
      securityGroup: workerSecurityGroup,
      environment: commonWorkerEnvironment,
      secrets: commonWorkerSecrets,
      stage,
    });

    const workerDefinitions = [researchWorker, documentWorker, verificationWorker];
    for (const runtime of workerDefinitions) {
      artifacts.grantReadWrite(runtime.taskDefinition.taskRole);
      manualReviewQueue.queue.grantSendMessages(runtime.taskDefinition.taskRole);
    }
    analysisQueue.queue.grantConsumeMessages(researchWorker.taskDefinition.taskRole);
    sourceFetchQueue.queue.grantConsumeMessages(documentWorker.taskDefinition.taskRole);
    filingQueue.queue.grantConsumeMessages(documentWorker.taskDefinition.taskRole);
    verificationQueue.queue.grantConsumeMessages(verificationWorker.taskDefinition.taskRole);
    sourceFetchQueue.queue.grantSendMessages(researchWorker.taskDefinition.taskRole);
    filingQueue.queue.grantSendMessages(researchWorker.taskDefinition.taskRole);
    verificationQueue.queue.grantSendMessages(researchWorker.taskDefinition.taskRole);

    apiContainer.addEnvironment('BENMO_ECS_CLUSTER', cluster.clusterArn);
    apiContainer.addEnvironment(
      'BENMO_RESEARCH_WORKER_TASK_DEFINITION',
      researchWorker.taskDefinition.taskDefinitionArn,
    );
    apiContainer.addEnvironment(
      'BENMO_WORKER_SUBNET_IDS',
      vpc.selectSubnets({ subnetType: ec2.SubnetType.PUBLIC }).subnetIds.join(','),
    );
    apiContainer.addEnvironment(
      'BENMO_WORKER_SECURITY_GROUP_IDS',
      workerSecurityGroup.securityGroupId,
    );
    apiTaskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:RunTask'],
        resources: [researchWorker.taskDefinition.taskDefinitionArn],
      }),
    );
    apiTaskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [
          researchWorker.taskDefinition.taskRole.roleArn,
          researchWorker.taskDefinition.executionRole!.roleArn,
        ],
        conditions: { StringEquals: { 'iam:PassedToService': 'ecs-tasks.amazonaws.com' } },
      }),
    );

    this.scaleWorkerOnQueue(researchWorker.service, analysisQueue.queue, 'ResearchQueueScaling');
    this.scaleWorkerOnQueue(documentWorker.service, sourceFetchQueue.queue, 'DocumentQueueScaling');
    this.scaleWorkerOnQueue(
      verificationWorker.service,
      verificationQueue.queue,
      'VerificationQueueScaling',
    );

    const workflowLogGroup = new logs.LogGroup(this, 'WorkflowLogGroup', {
      logGroupName: `/benmo/${stage}/workflows`,
      retention: logs.RetentionDays.SIX_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const analysisDefinition = this.analysisWorkflow({
      artifacts,
      cluster,
      worker: researchWorker,
      workerSecurityGroup,
    });
    const analysisStateMachine = new sfn.StateMachine(this, 'AnalysisWorkflow', {
      stateMachineName: `${namePrefix}-analysis`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromChainable(analysisDefinition),
      timeout: Duration.hours(12),
      tracingEnabled: true,
      logs: {
        destination: workflowLogGroup,
        includeExecutionData: false,
        level: sfn.LogLevel.ERROR,
      },
    });

    const enqueueVerification = new tasks.SqsSendMessage(this, 'EnqueueIndicatorVerification', {
      queue: verificationQueue.queue,
      messageBody: sfn.TaskInput.fromJsonPathAt('$'),
      resultPath: '$.enqueue_result',
    });
    const runVerificationWorker = new tasks.EcsRunTask(this, 'RunVerificationWorker', {
      integrationPattern: sfn.IntegrationPattern.RUN_JOB,
      cluster,
      taskDefinition: verificationWorker.taskDefinition,
      launchTarget: new tasks.EcsFargateLaunchTarget({
        platformVersion: ecs.FargatePlatformVersion.LATEST,
      }),
      assignPublicIp: true,
      securityGroups: [workerSecurityGroup],
      subnets: { subnetType: ec2.SubnetType.PUBLIC },
      containerOverrides: [
        {
          containerDefinition: verificationWorker.container,
          command: ['consume', '--worker', 'verification', '--once'],
        },
      ],
      resultPath: '$.worker_task',
      taskTimeout: sfn.Timeout.duration(Duration.minutes(30)),
    });
    runVerificationWorker.addRetry({
      errors: ['ECS.AmazonECSException', 'ECS.ECSException', 'States.Timeout'],
      interval: Duration.seconds(30),
      maxAttempts: 3,
      backoffRate: 2,
    });
    const verificationStateMachine = new sfn.StateMachine(this, 'VerificationWorkflow', {
      stateMachineName: `${namePrefix}-verification`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromChainable(
        enqueueVerification
          .next(runVerificationWorker)
          .next(new sfn.Succeed(this, 'VerificationCompleted')),
      ),
      timeout: Duration.minutes(5),
      tracingEnabled: true,
      logs: {
        destination: workflowLogGroup,
        includeExecutionData: false,
        level: sfn.LogLevel.ERROR,
      },
    });

    const scheduleGroup = new scheduler.CfnScheduleGroup(this, 'VerificationScheduleGroup', {
      name: `${namePrefix}-verification`,
      tags: [{ key: 'Application', value: 'benmo' }],
    });
    const schedulerTargetRole = new iam.Role(this, 'SchedulerTargetRole', {
      roleName: `${namePrefix}-scheduler-target`,
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      description: 'Allows EventBridge Scheduler to enqueue or start Benmo verification work.',
    });
    verificationQueue.queue.grantSendMessages(schedulerTargetRole);
    verificationStateMachine.grantStartExecution(schedulerTargetRole);

    const scheduleArn = Stack.of(this).formatArn({
      service: 'scheduler',
      resource: 'schedule',
      resourceName: `${scheduleGroup.ref}/*`,
    });
    for (const runtime of [researchWorker, verificationWorker]) {
      runtime.taskDefinition.taskRole.addToPrincipalPolicy(
        new iam.PolicyStatement({
          actions: [
            'scheduler:CreateSchedule',
            'scheduler:DeleteSchedule',
            'scheduler:GetSchedule',
            'scheduler:UpdateSchedule',
          ],
          resources: [scheduleArn],
        }),
      );
      runtime.taskDefinition.taskRole.addToPrincipalPolicy(
        new iam.PolicyStatement({
          actions: ['iam:PassRole'],
          resources: [schedulerTargetRole.roleArn],
          conditions: { StringEquals: { 'iam:PassedToService': 'scheduler.amazonaws.com' } },
        }),
      );
    }
    analysisStateMachine.grantStartExecution(apiTaskDefinition.taskRole);
    verificationStateMachine.grantStartExecution(apiTaskDefinition.taskRole);

    const dashboard = new cloudwatch.Dashboard(this, 'OperationsDashboard', {
      dashboardName: `${namePrefix}-operations`,
    });
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Public target latency and 5xx',
        left: [loadBalancer.metrics.targetResponseTime()],
        right: [loadBalancer.metrics.httpCodeTarget(elbv2.HttpCodeTarget.TARGET_5XX_COUNT)],
      }),
      new cloudwatch.GraphWidget({
        title: 'Frontend CPU and task count',
        left: [frontendService.metricCpuUtilization()],
        right: [frontendService.metricMemoryUtilization()],
      }),
      new cloudwatch.GraphWidget({
        title: 'RDS CPU and connections',
        left: [database.metricCPUUtilization()],
        right: [database.metricDatabaseConnections()],
      }),
      new cloudwatch.GraphWidget({
        title: 'Queue backlog',
        left: queueSet.map(({ queue }) => queue.metricApproximateNumberOfMessagesVisible()),
      }),
      new cloudwatch.GraphWidget({
        title: 'DLQ messages',
        left: queueSet.map(({ dlq }) => dlq.metricApproximateNumberOfMessagesVisible()),
      }),
    );
    for (const { dlq } of queueSet) {
      new cloudwatch.Alarm(this, `${dlq.node.id}Alarm`, {
        alarmName: `${dlq.queueName}-has-messages`,
        alarmDescription: `Messages in ${dlq.queueName} require operator review.`,
        metric: dlq.metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5) }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    }

    Tags.of(this).add('Application', 'benmo');
    Tags.of(this).add('Environment', stage, {
      excludeResourceTypes: ['aws:cdk:stack'],
    });
    Tags.of(this).add('ManagedBy', 'aws-cdk');

    new CfnOutput(this, 'ApiLoadBalancerDnsName', { value: loadBalancer.loadBalancerDnsName });
    new CfnOutput(this, 'ApiTaskDefinitionArn', {
      value: apiTaskDefinition.taskDefinitionArn,
    });
    new CfnOutput(this, 'PublicSiteUrl', { value: siteUrl.valueAsString });
    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'ApiSecurityGroupId', {
      value: apiSecurityGroup.securityGroupId,
    });
    new CfnOutput(this, 'PublicSubnetIds', {
      value: vpc
        .selectSubnets({ subnetType: ec2.SubnetType.PUBLIC })
        .subnetIds.join(','),
    });
    new CfnOutput(this, 'ArtifactsBucketName', { value: artifacts.bucketName });
    new CfnOutput(this, 'AnalysisQueueUrl', { value: analysisQueue.queue.queueUrl });
    new CfnOutput(this, 'AnalysisWorkflowArn', { value: analysisStateMachine.stateMachineArn });
    new CfnOutput(this, 'VerificationWorkflowArn', {
      value: verificationStateMachine.stateMachineArn,
    });
    new CfnOutput(this, 'VerificationScheduleGroupName', { value: scheduleGroup.ref });
    new CfnOutput(this, 'SchedulerTargetRoleArn', { value: schedulerTargetRole.roleArn });
  }

  private queueWithDlq(
    id: string,
    prefix: string,
    visibilityTimeout: Duration,
  ): QueueWithDlq {
    const physicalName = id.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
    const dlq = new sqs.Queue(this, `${id}Dlq`, {
      queueName: `${prefix}-${physicalName}-dlq`,
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      retentionPeriod: Duration.days(14),
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const queue = new sqs.Queue(this, `${id}Queue`, {
      queueName: `${prefix}-${physicalName}`,
      deadLetterQueue: { maxReceiveCount: 5, queue: dlq },
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      retentionPeriod: Duration.days(14),
      visibilityTimeout,
    });
    return { queue, dlq };
  }

  private createWorkerRuntime(props: {
    readonly id: string;
    readonly serviceName: string;
    readonly workerName: 'research' | 'document' | 'verification';
    readonly desiredCount: number;
    readonly cluster: ecs.Cluster;
    readonly imageUri: string;
    readonly securityGroup: ec2.SecurityGroup;
    readonly environment: Record<string, string>;
    readonly secrets: Record<string, ecs.Secret>;
    readonly stage: string;
  }): WorkerRuntime {
    const taskDefinition = new ecs.FargateTaskDefinition(this, `${props.id}TaskDefinition`, {
      family: `${props.serviceName}`,
      cpu: props.workerName === 'research' ? 1024 : 512,
      memoryLimitMiB: props.workerName === 'research' ? 2048 : 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    const logGroup = new logs.LogGroup(this, `${props.id}LogGroup`, {
      logGroupName: `/benmo/${props.stage}/worker/${props.workerName}`,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const container = taskDefinition.addContainer(props.workerName, {
      image: ecs.ContainerImage.fromRegistry(props.imageUri),
      command: ['consume', '--worker', props.workerName],
      environment: props.environment,
      secrets: props.secrets,
      logging: ecs.LogDrivers.awsLogs({
        logGroup,
        streamPrefix: props.workerName,
      }),
      healthCheck: {
        command: ['CMD', 'python', '-m', 'benmo_worker', 'doctor'],
        interval: Duration.seconds(60),
        timeout: Duration.seconds(15),
        retries: 3,
        startPeriod: Duration.seconds(30),
      },
    });
    const service = new ecs.FargateService(this, `${props.id}Service`, {
      serviceName: props.serviceName,
      cluster: props.cluster,
      taskDefinition,
      desiredCount: props.desiredCount,
      assignPublicIp: true,
      circuitBreaker: { rollback: true },
      enableECSManagedTags: true,
      propagateTags: ecs.PropagatedTagSource.SERVICE,
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      securityGroups: [props.securityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });
    return { taskDefinition, container, service };
  }

  private scaleWorkerOnQueue(
    service: ecs.FargateService,
    queue: sqs.Queue,
    id: string,
  ): void {
    service
      .autoScaleTaskCount({ minCapacity: 0, maxCapacity: 10 })
      .scaleOnMetric(id, {
        metric: queue.metricApproximateNumberOfMessagesVisible(),
        adjustmentType: appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        scalingSteps: [
          { upper: 0, change: -1 },
          { lower: 1, upper: 10, change: 1 },
          { lower: 10, change: 3 },
        ],
        cooldown: Duration.minutes(2),
      });
  }

  private analysisWorkflow(props: {
    readonly artifacts: s3.Bucket;
    readonly cluster: ecs.Cluster;
    readonly worker: WorkerRuntime;
    readonly workerSecurityGroup: ec2.SecurityGroup;
  }): sfn.IChainable {
    const stages = [
      'normalize-fact',
      'generate-candidates',
      'research-edge',
      'verify-citations',
      'entailment',
      'adversarial-search',
      'compile-spec',
      'publication-gate',
      'create-version',
      'publish-review',
    ] as const;

    const outputUri = (index: number, stage: string): string =>
      sfn.JsonPath.format(
        `s3://${props.artifacts.bucketName}/workflow-runs/{}/${String(index + 1).padStart(2, '0')}-${stage}.json`,
        sfn.JsonPath.stringAt('$$.Execution.Name'),
      );

    let chain: sfn.Chain | undefined;
    stages.forEach((stage, index) => {
      const inputUri =
        index === 0 ? sfn.JsonPath.stringAt('$.input_s3_uri') : outputUri(index - 1, stages[index - 1]);
      const task = new tasks.EcsRunTask(this, `Analysis${index + 1}${this.pascalCase(stage)}`, {
        integrationPattern: sfn.IntegrationPattern.RUN_JOB,
        cluster: props.cluster,
        taskDefinition: props.worker.taskDefinition,
        launchTarget: new tasks.EcsFargateLaunchTarget({
          platformVersion: ecs.FargatePlatformVersion.LATEST,
        }),
        assignPublicIp: true,
        securityGroups: [props.workerSecurityGroup],
        subnets: { subnetType: ec2.SubnetType.PUBLIC },
        containerOverrides: [
          {
            containerDefinition: props.worker.container,
            command: ['run-stage', stage],
            environment: [
              { name: 'BENMO_STAGE_INPUT', value: inputUri },
              { name: 'BENMO_STAGE_OUTPUT', value: outputUri(index, stage) },
            ],
          },
        ],
        resultPath: '$.last_task',
        taskTimeout: sfn.Timeout.duration(Duration.hours(2)),
      });
      task.addRetry({
        errors: ['ECS.AmazonECSException', 'ECS.ECSException', 'States.Timeout'],
        interval: Duration.seconds(30),
        maxAttempts: 3,
        backoffRate: 2,
      });
      chain = chain === undefined ? sfn.Chain.start(task) : chain.next(task);
    });

    return chain!.next(new sfn.Succeed(this, 'AnalysisCompleted'));
  }

  private pascalCase(value: string): string {
    return value
      .split('-')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join('');
  }
}
