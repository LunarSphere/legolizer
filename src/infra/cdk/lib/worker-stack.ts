import { CfnOutput, Duration, Fn, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { containerEnv, MIN_MEMORY_MIB, PROVIDER_KEYS } from './config';
import { DataStack } from './data-stack';

export interface WorkerStackProps extends StackProps {
  data: DataStack;
  imageTag: string;
  cpu: number;
  memoryMiB: number;
  idleMinutes: number;
}

/**
 * One on-demand Fargate worker with no public IPv4 and no inbound traffic.
 * The Vercel API starts it with RunTask when jobs are queued; it exits after
 * `idleMinutes` without work, so idle time costs nothing.
 */
export class WorkerStack extends Stack {
  constructor(scope: Construct, id: string, props: WorkerStackProps) {
    super(scope, id, props);
    const { data } = props;
    if (props.memoryMiB < MIN_MEMORY_MIB) {
      throw new Error(`The worker needs at least ${MIN_MEMORY_MIB} MiB of memory`);
    }

    // IPv6-only subnets behind an egress-only gateway: tasks reach ECR, S3, DynamoDB,
    // CloudWatch Logs, Secrets Manager, and the model providers over IPv6, so there is
    // no NAT gateway, no VPC endpoint, and no public IPv4 address to pay for.
    const vpc = new ec2.CfnVPC(this, 'Vpc', {
      cidrBlock: '10.42.0.0/16',
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });
    const ipv6 = new ec2.CfnVPCCidrBlock(this, 'Ipv6', {
      vpcId: vpc.ref,
      amazonProvidedIpv6CidrBlock: true,
    });
    const egress = new ec2.CfnEgressOnlyInternetGateway(this, 'Egress', { vpcId: vpc.ref });
    const routes = new ec2.CfnRouteTable(this, 'Routes', { vpcId: vpc.ref });
    new ec2.CfnRoute(this, 'Ipv6Default', {
      routeTableId: routes.ref,
      destinationIpv6CidrBlock: '::/0',
      egressOnlyInternetGatewayId: egress.ref,
    });
    const subnets = [0, 1].map((index) => {
      const subnet = new ec2.CfnSubnet(this, `Subnet${index}`, {
        vpcId: vpc.ref,
        availabilityZone: Fn.select(index, Fn.getAzs()),
        ipv6Native: true,
        ipv6CidrBlock: Fn.select(index, Fn.cidr(Fn.select(0, vpc.attrIpv6CidrBlocks), 2, '64')),
        assignIpv6AddressOnCreation: true,
        privateDnsNameOptionsOnLaunch: {
          HostnameType: 'resource-name',
          EnableResourceNameDnsAAAARecord: true,
          EnableResourceNameDnsARecord: false,
        },
      });
      subnet.addResourceDependency(ipv6);
      new ec2.CfnSubnetRouteTableAssociation(this, `Subnet${index}Routes`, {
        subnetId: subnet.ref,
        routeTableId: routes.ref,
      });
      return subnet;
    });
    const group = new ec2.CfnSecurityGroup(this, 'WorkerGroup', {
      vpcId: vpc.ref,
      groupDescription: 'Legolizer worker: outbound IPv6 only, no inbound',
      securityGroupEgress: [{ ipProtocol: '-1', cidrIpv6: '::/0' }],
    });

    const cluster = new ecs.CfnCluster(this, 'Cluster');
    const logGroup = new logs.LogGroup(this, 'Logs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const task = new ecs.FargateTaskDefinition(this, 'Task', {
      cpu: props.cpu,
      memoryLimitMiB: props.memoryMiB,
      ephemeralStorageGiB: 30,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    // IPv6-only tasks must pull through ECR's dual-stack registry name.
    const image = `${this.account}.dkr-ecr.${this.region}.on.aws/${data.repository.repositoryName}:${props.imageTag}`;
    data.repository.grantPull(task.obtainExecutionRole());
    task.addContainer('worker', {
      image: ecs.ContainerImage.fromRegistry(image),
      environment: {
        ...containerEnv(),
        LEGOLIZER_BUCKET: data.bucket.bucketName,
        LEGOLIZER_TABLE: data.table.tableName,
        LEGOLIZER_IDLE_EXIT_SECONDS: String(props.idleMinutes * 60),
        AWS_REGION: this.region,
        AWS_DEFAULT_REGION: this.region,
        AWS_USE_DUALSTACK_ENDPOINT: 'true',
      },
      secrets: Object.fromEntries(
        PROVIDER_KEYS.map((key) => [key, ecs.Secret.fromSecretsManager(data.providerKeys, key)]),
      ),
      logging: ecs.LogDrivers.awsLogs({ logGroup, streamPrefix: 'worker' }),
      stopTimeout: Duration.seconds(30),
    });
    data.bucket.grantReadWrite(task.taskRole);
    data.table.grantReadWriteData(task.taskRole);

    // Credentials for the Vercel function: queue jobs, read builds, presign assets, start the worker.
    // RunTask by family (no revision) starts the latest revision, so a worker-only
    // deploy takes effect without updating the Vercel env.
    const api = new iam.User(this, 'VercelApi');
    data.bucket.grantReadWrite(api);
    data.table.grantReadWriteData(api);
    api.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:RunTask'],
        resources: [
          this.formatArn({ service: 'ecs', resource: 'task-definition', resourceName: `${task.family}:*` }),
        ],
        conditions: { ArnEquals: { 'ecs:cluster': cluster.attrArn } },
      }),
    );
    api.addToPolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [task.taskRole.roleArn, task.obtainExecutionRole().roleArn],
        conditions: { StringEquals: { 'iam:PassedToService': 'ecs-tasks.amazonaws.com' } },
      }),
    );

    new CfnOutput(this, 'ClusterName', { value: cluster.ref });
    new CfnOutput(this, 'TaskDefinitionFamily', { value: task.family });
    new CfnOutput(this, 'Subnets', { value: Fn.join(',', subnets.map((subnet) => subnet.ref)) });
    new CfnOutput(this, 'SecurityGroup', { value: group.attrGroupId });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'VercelUserName', { value: api.userName });
  }
}
