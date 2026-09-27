import { CfnOutput, Stack, StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { DataStack } from './data-stack';

export interface DeployStackProps extends StackProps {
  data: DataStack;
  githubRepo: string;
  githubEnvironment: string;
  /** Reuse an account's existing GitHub OIDC provider; IAM allows only one per URL. */
  oidcProviderArn?: string;
}

/** Role that GitHub Actions assumes (OIDC, no stored keys) to run deploy.sh. */
export class DeployStack extends Stack {
  constructor(scope: Construct, id: string, props: DeployStackProps) {
    super(scope, id, props);
    const issuer = 'token.actions.githubusercontent.com';
    const provider = props.oidcProviderArn
      ? iam.OidcProviderNative.fromOidcProviderArn(this, 'GitHub', props.oidcProviderArn)
      : new iam.OidcProviderNative(this, 'GitHub', {
          url: `https://${issuer}`,
          clientIds: ['sts.amazonaws.com'],
        });

    const role = new iam.Role(this, 'DeployRole', {
      description: `GitHub Actions deploys from ${props.githubRepo} (${props.githubEnvironment})`,
      assumedBy: new iam.OpenIdConnectPrincipal(provider, {
        StringEquals: {
          [`${issuer}:aud`]: 'sts.amazonaws.com',
          [`${issuer}:sub`]: `repo:${props.githubRepo}:environment:${props.githubEnvironment}`,
        },
      }),
    });
    // cdk deploy runs through the bootstrap roles, which hold the CloudFormation permissions.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sts:AssumeRole'],
        resources: [`arn:${this.partition}:iam::${this.account}:role/cdk-*`],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:ListAccountSettings', 'ecs:PutAccountSetting'],
        resources: ['*'],
      }),
    );
    props.data.repository.grantPush(role);

    new CfnOutput(this, 'DeployRoleArn', { value: role.roleArn });
  }
}
