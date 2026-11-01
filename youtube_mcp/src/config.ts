import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface Config {
  apiKey?: string;
  serviceAccountFile?: string;
  timeout: number;
}

function applyEnvFile(filePath: string): void {
  if (!existsSync(filePath)) return;

  for (const rawLine of readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;

    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!process.env[key]) process.env[key] = value;
  }
}

function loadLocalEnv(): void {
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    process.env.YOUTUBE_ENV_FILE,
    resolve(here, '..', '..', 'keys', '.env'),
    resolve(here, '..', '..', '..', 'keys', '.env')
  ].filter((path): path is string => Boolean(path));

  for (const path of candidates) applyEnvFile(path);
}

export function loadConfig(): Config {
  loadLocalEnv();

  const apiKey = process.env.YOUTUBE_API_KEY?.trim() || undefined;
  const serviceAccountFile = process.env.YOUTUBE_SERVICE_ACCOUNT_FILE?.trim() || undefined;

  if (!apiKey && !serviceAccountFile) {
    throw new Error(
      'YouTube credentials are not configured. Set YOUTUBE_SERVICE_ACCOUNT_FILE to a Google service account JSON path, or set YOUTUBE_API_KEY.'
    );
  }

  const timeoutStr = process.env.YOUTUBE_TIMEOUT;
  const timeout = timeoutStr ? parseInt(timeoutStr, 10) : 30000;

  if (timeout <= 0) {
    throw new Error('YOUTUBE_TIMEOUT must be a positive number');
  }

  return { apiKey, serviceAccountFile, timeout };
}

export const YOUTUBE_API_BASE = 'https://www.googleapis.com/youtube/v3';
export const SPONSORBLOCK_API_BASE = 'https://sponsor.ajay.app/api';
