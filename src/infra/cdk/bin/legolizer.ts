import { App } from 'aws-cdk-lib';
import { DataStack } from '../lib/data-stack';
import { WorkerStack } from '../lib/worker-stack';

const app = new App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION };
const context = (key: string, fallback: string): string => app.node.tryGetContext(key) ?? fallback;

const data = new DataStack(app, 'LegolizerData', { env });

// The worker needs an image already pushed to ECR, so it is synthesized only with a tag
// (deploy.sh pushes the locally validated image first).
const imageTag = app.node.tryGetContext('imageTag');
if (imageTag) {
  new WorkerStack(app, 'LegolizerWorker', {
    env,
    data,
    imageTag,
    cpu: Number(context('cpu', '2048')),
    memoryMiB: Number(context('memoryMiB', '12288')),
    idleMinutes: Number(context('idleMinutes', '15')),
  });
}
