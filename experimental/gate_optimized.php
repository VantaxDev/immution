<?php
/**
 * Immution Gate - Optimized Version (No External Dependencies)
 * 
 * Performance improvements using only PHP standard library:
 * 1. Static caching within request - avoid repeated operations
 * 2. Memory-mapped banned IP lookup - O(1) ban check
 * 3. Optimized JSON parsing - compact format
 * 4. Early exit paths - minimize processing for clean IPs
 * 5. Reduced function calls - inline where possible
 */

declare(strict_types=1);

// =============================================================================
// CONFIGURATION
// =============================================================================

define('IMMUTION_SHM_DIR', '/dev/shm/immution');
define('IMMUTION_THRESHOLD', 50);
define('IMMUTION_ENABLED', true);

// Memory-mapped banned IP file (created by Python daemon)
define('IMMUTION_MMAP_FILE', '/dev/shm/immution/banned.mmap');
define('IMMUTION_MMAP_SIZE', 65536);
define('IMMUTION_MMAP_ENTRY_SIZE', 8);

// Logging
define('IMMUTION_LOG_ENABLED', true);
define('IMMUTION_LOG_DIR', '/var/log/immution');
define('IMMUTION_LOG_FILE', IMMUTION_LOG_DIR . '/blocked.csv');

// Exclusions
define('IMMUTION_EXCLUDE_PATHS', [
    '#^/api/health#',
    '#^/cron/#',
]);

define('IMMUTION_WHITELIST', []);

// =============================================================================
// OPTIMIZED FUNCTIONS
// =============================================================================

/**
 * Get client IP - cached for the request lifecycle.
 */
function immution_get_client_ip(): string 
{
    static $ip = null;
    if ($ip !== null) return $ip;
    
    // Check headers in priority order
    foreach (['HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP', 'REMOTE_ADDR'] as $h) {
        if (!empty($_SERVER[$h])) {
            $candidate = $_SERVER[$h];
            if (($pos = strpos($candidate, ',')) !== false) {
                $candidate = substr($candidate, 0, $pos);
            }
            $candidate = trim($candidate);
            if (filter_var($candidate, FILTER_VALIDATE_IP)) {
                return $ip = $candidate;
            }
        }
    }
    return $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
}

/**
 * Check if path is excluded - cached result.
 */
function immution_is_excluded_path(): bool 
{
    static $result = null;
    if ($result !== null) return $result;
    
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';
    foreach (IMMUTION_EXCLUDE_PATHS as $pattern) {
        if (preg_match($pattern, $path)) {
            return $result = true;
        }
    }
    return $result = false;
}

/**
 * Check if IP is whitelisted - cached result.
 */
function immution_is_whitelisted(string $ip): bool 
{
    static $cache = [];
    if (isset($cache[$ip])) return $cache[$ip];
    
    foreach (IMMUTION_WHITELIST as $entry) {
        if (strpos($entry, '/') !== false) {
            // CIDR check
            list($subnet, $bits) = explode('/', $entry);
            $ipLong = ip2long($ip);
            $subnetLong = ip2long($subnet);
            $mask = -1 << (32 - (int)$bits);
            if (($ipLong & $mask) === ($subnetLong & $mask)) {
                return $cache[$ip] = true;
            }
        } elseif ($ip === $entry) {
            return $cache[$ip] = true;
        }
    }
    return $cache[$ip] = false;
}

/**
 * Fast IP hash for mmap lookup - must match Python exactly.
 */
function immution_ip_hash(string $ip): int 
{
    $hash = md5($ip, true);
    return unpack('V', substr($hash, 0, 4))[1] % IMMUTION_MMAP_SIZE;
}

/**
 * Check if IP is banned using memory-mapped file.
 * O(1) lookup without JSON parsing.
 */
function immution_check_mmap_banned(string $ip): bool
{
    static $mmap = null;
    static $initialized = false;
    
    // Initialize once per request
    if (!$initialized) {
        $initialized = true;
        if (file_exists(IMMUTION_MMAP_FILE)) {
            $mmap = @file_get_contents(IMMUTION_MMAP_FILE);
            if ($mmap === false || strlen($mmap) < IMMUTION_MMAP_SIZE * IMMUTION_MMAP_ENTRY_SIZE) {
                $mmap = null;
            }
        }
    }
    
    if ($mmap === null) {
        return false;
    }
    
    $idx = immution_ip_hash($ip);
    $offset = $idx * IMMUTION_MMAP_ENTRY_SIZE;
    $entry = substr($mmap, $offset, 8);
    
    // Empty entry = not banned
    if ($entry === "\0\0\0\0\0\0\0\0") {
        return false;
    }
    
    // Verify checksum matches this IP
    $stored = unpack('V', substr($entry, 0, 4))[1];
    $expected = unpack('V', substr(md5($ip, true), 0, 4))[1];
    
    return $stored === $expected;
}

/**
 * Load IP data from JSON file.
 */
function immution_load_ip_data(string $ip)
{
    $filepath = IMMUTION_SHM_DIR . '/' . str_replace(':', '_', $ip) . '.txt';
    
    if (!file_exists($filepath)) {
        return null;
    }
    
    $content = @file_get_contents($filepath);
    if ($content === false) {
        return null;
    }
    
    $data = @json_decode($content, true);
    return is_array($data) ? $data : null;
}

/**
 * Log blocked request to CSV.
 */
function immution_log_block(string $ip, array $data)
{
    if (!IMMUTION_LOG_ENABLED) return;
    
    if (!is_dir(IMMUTION_LOG_DIR)) {
        @mkdir(IMMUTION_LOG_DIR, 0755, true);
    }
    
    $write_header = !file_exists(IMMUTION_LOG_FILE);
    $fp = @fopen(IMMUTION_LOG_FILE, 'a');
    if ($fp === false) return;
    
    if (flock($fp, LOCK_EX)) {
        if ($write_header) {
            fputcsv($fp, ['timestamp','ip','domain','request_uri','score','requests','errors_404','probes','user_agent','reasons']);
        }
        
        $reasons = $data['reasons'] ?? [];
        fputcsv($fp, [
            date('Y-m-d H:i:s'),
            $ip,
            $_SERVER['HTTP_HOST'] ?? $_SERVER['SERVER_NAME'] ?? 'unknown',
            $_SERVER['REQUEST_URI'] ?? '/',
            $data['score'] ?? 0,
            $data['requests'] ?? 0,
            $data['errors_404'] ?? 0,
            $data['probes'] ?? 0,
            $_SERVER['HTTP_USER_AGENT'] ?? '',
            implode(' | ', array_slice($reasons, 0, 5))
        ]);
        
        flock($fp, LOCK_UN);
    }
    fclose($fp);
}

/**
 * Show ban page and exit.
 */
function immution_show_ban_page(string $ip)
{
    http_response_code(403);
    header('Cache-Control: no-cache, no-store, must-revalidate');
    header('Content-Type: text/html; charset=UTF-8');
    
    $lang = (stripos($_SERVER['HTTP_ACCEPT_LANGUAGE'] ?? '', 'it') === 0) ? 'it' : 'en';
    
    $t = $lang === 'it' ? [
        'title' => 'Accesso Negato',
        'msg1' => 'Il tuo IP è stato temporaneamente bloccato.',
        'msg2' => 'Attendi qualche minuto e riprova.',
        'retry' => 'Riprova'
    ] : [
        'title' => 'Access Denied',
        'msg1' => 'Your IP has been temporarily blocked.',
        'msg2' => 'Please wait a few minutes and try again.',
        'retry' => 'Retry'
    ];
    
    // Minimal HTML for fast response
    echo <<<HTML
<!DOCTYPE html><html lang="{$lang}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{$t['title']}</title>
<style>*{margin:0;padding:0}body{font-family:system-ui,sans-serif;background:#1a1a2e;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#fff}.c{background:rgba(255,255,255,.05);border-radius:16px;padding:40px;max-width:400px;text-align:center}.i{font-size:48px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#ff6b6b}p{color:#888;margin-bottom:12px}.n{background:rgba(255,255,255,.05);border-radius:8px;padding:12px;font-size:13px;color:#666;margin-top:16px}code{color:#ff6b6b}.r{margin-top:20px}.r a{color:#4ecdc4;text-decoration:none}</style>
</head><body><div class="c">
<div class="i">⛔</div><h1>{$t['title']}</h1>
<p>{$t['msg1']}</p><p>{$t['msg2']}</p>
<div class="n">IP: <code>{$ip}</code></div>
<div class="r"><a href="javascript:location.reload()">↻ {$t['retry']}</a></div>
</div></body></html>
HTML;
    exit();
}

// =============================================================================
// MAIN EXECUTION - OPTIMIZED FLOW
// =============================================================================

if (!IMMUTION_ENABLED) return;

// Fast exit: excluded paths
if (immution_is_excluded_path()) return;

$ip = immution_get_client_ip();

// Fast exit: localhost
if ($ip[0] === '1' && strncmp($ip, '127.', 4) === 0) return;
if ($ip === '::1') return;

// Fast exit: whitelist
if (IMMUTION_WHITELIST && immution_is_whitelisted($ip)) return;

// OPTIMIZATION 1: Check mmap banned table first (O(1), no JSON parsing)
if (immution_check_mmap_banned($ip)) {
    $data = immution_load_ip_data($ip) ?? ['score' => IMMUTION_THRESHOLD, 'banned' => true];
    immution_log_block($ip, $data);
    immution_show_ban_page($ip);
}

// OPTIMIZATION 2: Check JSON file only if not in mmap
$data = immution_load_ip_data($ip);

// Fast exit: no data = clean IP
if ($data === null) return;

// Check score threshold
if (!empty($data['banned']) || ($data['score'] ?? 0) >= IMMUTION_THRESHOLD) {
    immution_log_block($ip, $data);
    immution_show_ban_page($ip);
}
