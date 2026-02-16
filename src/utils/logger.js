import chalk from 'chalk';

const PREFIX = {
  info: chalk.blue('ℹ'),
  success: chalk.green('✓'),
  warn: chalk.yellow('⚠'),
  error: chalk.red('✗'),
  step: chalk.cyan('→'),
};

export const log = {
  info: (msg) => console.log(`${PREFIX.info} ${msg}`),
  success: (msg) => console.log(`${PREFIX.success} ${msg}`),
  warn: (msg) => console.log(`${PREFIX.warn} ${msg}`),
  error: (msg) => console.error(`${PREFIX.error} ${msg}`),
  step: (msg) => console.log(`${PREFIX.step} ${msg}`),
  blank: () => console.log(),
  header: (msg) => {
    console.log();
    console.log(chalk.bold.white(msg));
    console.log(chalk.dim('─'.repeat(Math.min(msg.length + 4, 60))));
  },
  dim: (msg) => console.log(chalk.dim(`  ${msg}`)),
  json: (data) => console.log(JSON.stringify(data, null, 2)),
};
