import { CfnOutput, Duration, RemovalPolicy, SecretValue, Stack, StackProps } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { KeyElement, PROVIDER_KEYS, tableSchema } from './config';

/** Image registry, generated assets, build/job metadata, and provider keys. */
export class DataStack extends Stack {
  readonly repository: ecr.Repository;
  readonly bucket: s3.Bucket;
  readonly table: dynamodb.TableV2;
  readonly providerKeys: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    this.repository = new ecr.Repository(this, 'Images', {
      imageScanOnPush: true,
      lifecycleRules: [{ maxImageCount: 3 }],
      removalPolicy: RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    this.bucket = new s3.Bucket(this, 'Assets', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      lifecycleRules: [{ prefix: 'uploads/', expiration: Duration.days(30) }],
      // Assets are only reachable through short-lived presigned links from the API; the
      // studio's WebGL loader fetches packed.mpd cross-origin.
      cors: [{ allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.HEAD], allowedOrigins: ['*'] }],
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const schema = tableSchema();
    const types = {
      S: dynamodb.AttributeType.STRING,
      N: dynamodb.AttributeType.NUMBER,
      B: dynamodb.AttributeType.BINARY,
    };
    const attribute = (keys: KeyElement[], keyType: KeyElement['KeyType']) => {
      const name = keys.find((key) => key.KeyType === keyType)?.AttributeName;
      if (!name) return undefined;
      const definition = schema.AttributeDefinitions.find((a) => a.AttributeName === name);
      return { name, type: types[definition!.AttributeType] };
    };
    this.table = new dynamodb.TableV2(this, 'Metadata', {
      partitionKey: attribute(schema.KeySchema, 'HASH')!,
      billing: dynamodb.Billing.onDemand(),
      globalSecondaryIndexes: schema.GlobalSecondaryIndexes.map((index) => ({
        indexName: index.IndexName,
        partitionKey: attribute(index.KeySchema, 'HASH')!,
        sortKey: attribute(index.KeySchema, 'RANGE'),
        projectionType: dynamodb.ProjectionType[index.Projection.ProjectionType],
      })),
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.providerKeys = new secretsmanager.Secret(this, 'ProviderKeys', {
      description: 'Legolizer provider API keys, written by src/infra/scripts/deploy.sh',
      secretObjectValue: Object.fromEntries(
        PROVIDER_KEYS.map((key) => [key, SecretValue.unsafePlainText('')]),
      ),
      removalPolicy: RemovalPolicy.DESTROY,
    });

    new CfnOutput(this, 'RepositoryUri', { value: this.repository.repositoryUri });
    new CfnOutput(this, 'BucketName', { value: this.bucket.bucketName });
    new CfnOutput(this, 'TableName', { value: this.table.tableName });
    new CfnOutput(this, 'SecretArn', { value: this.providerKeys.secretArn });
  }
}
