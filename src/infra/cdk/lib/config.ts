import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const infra = join(__dirname, '..', '..');

// Secrets Manager fields injected into the container; deploy.sh fills them from .env.
export const PROVIDER_KEYS = ['OPENAI_API_KEY', 'GROK_API_KEY'];

export const MIN_MEMORY_MIB = 12 * 1024;

export function containerEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const line of readFileSync(join(infra, 'container.env'), 'utf8').split('\n')) {
    const text = line.trim();
    if (!text || text.startsWith('#')) continue;
    const at = text.indexOf('=');
    env[text.slice(0, at).trim()] = text.slice(at + 1).trim();
  }
  return env;
}

export interface KeyElement {
  AttributeName: string;
  KeyType: 'HASH' | 'RANGE';
}

export interface TableSchema {
  AttributeDefinitions: { AttributeName: string; AttributeType: 'S' | 'N' | 'B' }[];
  KeySchema: KeyElement[];
  GlobalSecondaryIndexes: {
    IndexName: string;
    KeySchema: KeyElement[];
    Projection: { ProjectionType: 'ALL' | 'KEYS_ONLY' };
  }[];
}

export function tableSchema(): TableSchema {
  return JSON.parse(readFileSync(join(infra, 'table-schema.json'), 'utf8'));
}
