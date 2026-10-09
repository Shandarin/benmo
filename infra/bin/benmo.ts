#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { BenmoPlatformStack } from '../lib/benmo-platform-stack';

const app = new cdk.App();

new BenmoPlatformStack(app, 'BenmoPlatformStack', {
  description: 'Benmo auditable causal hypothesis platform - production backend and workers',
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
  },
  terminationProtection: true,
});

