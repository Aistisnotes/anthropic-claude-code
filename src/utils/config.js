import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { existsSync, mkdirSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..', '..');

export const config = {
  // Meta Ad Library API
  meta: {
    apiBase: 'https://graph.facebook.com/v21.0',
    adLibraryEndpoint: '/ads_archive',
    // Token loaded from env — required for API access
    accessToken: process.env.META_ACCESS_TOKEN || null,
    // Default search params
    defaultCountry: 'US',
    defaultAdType: 'ALL',
    // Rate limiting
    requestDelayMs: 500,
    maxPagesPerScan: 20,
    resultsPerPage: 100,
  },

  // Ad selection thresholds (days)
  selection: {
    activeWinnerMaxDays: 14,
    provenRecentMaxDays: 30,
    strategicDirectionMaxDays: 7,
    recentModerateMaxDays: 60,
    skipOlderThanDays: 180,
    minPrimaryTextWords: 50,
  },

  // Impression level thresholds (Meta returns ranges like "1K-5K")
  impressions: {
    highMin: 50000,
    moderateMin: 10000,
    lowMax: 1000,
  },

  // Claude API (for deep analysis)
  claude: {
    apiKey: process.env.ANTHROPIC_API_KEY || null,
    model: process.env.CLAUDE_MODEL || 'claude-sonnet-4-5-20250929',
    maxTokens: 4096,
    maxConcurrent: 3,
    retryAttempts: 2,
    retryDelayMs: 1000,
  },

  // Output paths
  paths: {
    root: PROJECT_ROOT,
    data: join(PROJECT_ROOT, 'data'),
    scans: join(PROJECT_ROOT, 'data', 'scans'),
    downloads: join(PROJECT_ROOT, 'data', 'downloads'),
    reports: join(PROJECT_ROOT, 'data', 'reports'),
  },
};

/** Ensure output directories exist */
export function ensureDataDirs() {
  for (const dir of [config.paths.scans, config.paths.downloads, config.paths.reports]) {
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
  }
}
