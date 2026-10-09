#!/bin/sh
set -eu

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

create_queue_with_dlq() {
  queue_name="$1"
  visibility_timeout="$2"
  dlq_name="${queue_name}-dlq"

  dlq_url="$(awslocal sqs create-queue \
    --queue-name "$dlq_name" \
    --attributes MessageRetentionPeriod=1209600 \
    --query QueueUrl \
    --output text)"
  dlq_arn="$(awslocal sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)"
  attributes="$(printf '{\"VisibilityTimeout\":\"%s\",\"MessageRetentionPeriod\":\"1209600\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"%s\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}' "$visibility_timeout" "$dlq_arn")"

  awslocal sqs create-queue \
    --queue-name "$queue_name" \
    --attributes "$attributes" \
    >/dev/null
}

if ! awslocal s3api head-bucket --bucket benmo-local-artifacts >/dev/null 2>&1; then
  awslocal s3api create-bucket --bucket benmo-local-artifacts >/dev/null
fi
awslocal s3api put-bucket-versioning \
  --bucket benmo-local-artifacts \
  --versioning-configuration Status=Enabled

create_queue_with_dlq analysis-requested 900
create_queue_with_dlq source-fetch 300
create_queue_with_dlq filing-processing 900
create_queue_with_dlq indicator-verification 300
create_queue_with_dlq manual-review 120
create_queue_with_dlq event-ingestion 120

echo "Benmo LocalStack resources are ready."

