#!/usr/bin/env node

import { program } from 'commander';
import { registerScanCommand } from '../src/commands/scan.js';
import { registerMarketCommand } from '../src/commands/market.js';
import { registerCompareCommand } from '../src/commands/compare.js';

program
  .name('meta-ads')
  .description('Market research pipeline — surgical ad intelligence from Meta Ad Library')
  .version('0.1.0');

registerScanCommand(program);
registerMarketCommand(program);
registerCompareCommand(program);

program.parse();
