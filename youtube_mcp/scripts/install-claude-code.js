#!/usr/bin/env node

import { execSync } from 'child_process';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distPath = resolve(__dirname, '..', 'dist', 'index.js');

const apiKey = process.env.YOUTUBE_API_KEY;
const serviceAccountFile = process.env.YOUTUBE_SERVICE_ACCOUNT_FILE;

if (!apiKey && !serviceAccountFile) {
  console.error('Error: set YOUTUBE_SERVICE_ACCOUNT_FILE or YOUTUBE_API_KEY before running this script.');
  process.exit(1);
}

const envFlag = serviceAccountFile
  ? `YOUTUBE_SERVICE_ACCOUNT_FILE=${serviceAccountFile}`
  : `YOUTUBE_API_KEY=${apiKey}`;

try {
  const cmd = `claude mcp add youtube-mcp -e ${envFlag} -- node ${distPath}`;
  console.log('Adding YouTube MCP server to Claude Code...');
  execSync(cmd, { stdio: 'inherit' });
  console.log('YouTube MCP server added successfully!');
} catch (error) {
  console.error('Failed to add MCP server. You can add it manually:');
  console.error(`  claude mcp add youtube-mcp -e ${envFlag} -- node ${distPath}`);
  process.exit(1);
}
