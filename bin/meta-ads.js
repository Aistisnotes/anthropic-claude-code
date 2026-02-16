#!/usr/bin/env node

import { program } from 'commander';
import { registerScanCommand } from '../src/commands/scan.js';

program
  .name('meta-ads')
  .description('Market research pipeline — surgical ad intelligence from Meta Ad Library')
  .version('0.1.0');

registerScanCommand(program);

// Placeholder registrations for Session 2 & 3
// registerMarketCommand(program);
// registerCompareCommand(program);

program.parse();
