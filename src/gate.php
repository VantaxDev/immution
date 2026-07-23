<?php
/**
 * Immution PHP gate v0.1.0-rc3.
 *
 * Loaded with auto_prepend_file. The gate only reads state produced by the
 * daemon. It defaults to monitor mode: events are logged but requests are not
 * blocked until the administrator explicitly changes the mode to "block".
 */

declare(strict_types=1);

const IMMUTION_CONFIG_FILE = '/etc/immution/gate-config.php';

/** @return array<string,mixed> */
function immution_config(): array
{
    static $config = null;
    if (is_array($config)) {
        return $config;
    }

    $defaults = [
        'enabled' => true,
        'mode' => 'monitor',
        'runtime_dir' => '/run/immution',
        'log_enabled' => true,
        'log_file' => '/var/log/immution/events.csv',
        'whitelist' => [],
        'exclude_paths' => [
            '#^/api/health(?:/|$)#',
            '#^/cron(?:/|$)#',
        ],
    ];

    $loaded = [];
    if (is_file(IMMUTION_CONFIG_FILE) && is_readable(IMMUTION_CONFIG_FILE)) {
        try {
            $value = require IMMUTION_CONFIG_FILE;
            if (is_array($value)) {
                $loaded = $value;
            }
        } catch (Throwable $error) {
            // A broken optional config must not take down every PHP request.
            $loaded = [];
        }
    }

    $config = array_replace($defaults, $loaded);
    if (!in_array($config['mode'], ['monitor', 'block'], true)) {
        $config['mode'] = 'monitor';
    }
    if (!is_array($config['whitelist'])) {
        $config['whitelist'] = [];
    }
    if (!is_array($config['exclude_paths'])) {
        $config['exclude_paths'] = [];
    }
    return $config;
}

/** @return string|null */
function immution_client_ip()
{
    // Do not trust client-controlled forwarding headers here. When Apache is
    // behind a reverse proxy/CDN, configure mod_remoteip so REMOTE_ADDR and the
    // first field in the access log contain the same effective client IP.
    $ip = $_SERVER['REMOTE_ADDR'] ?? '';
    return filter_var($ip, FILTER_VALIDATE_IP) !== false ? $ip : null;
}

function immution_ip_filename(string $ip): string
{
    return str_replace(':', '_', $ip) . '.json';
}

function immution_ip_in_cidr(string $ip, string $cidr): bool
{
    if (strpos($cidr, '/') === false) {
        return false;
    }
    list($network, $prefixText) = explode('/', $cidr, 2);
    if (!ctype_digit($prefixText)) {
        return false;
    }

    $ipBytes = @inet_pton($ip);
    $networkBytes = @inet_pton($network);
    if ($ipBytes === false || $networkBytes === false || strlen($ipBytes) !== strlen($networkBytes)) {
        return false;
    }

    $prefix = (int)$prefixText;
    $totalBits = strlen($ipBytes) * 8;
    if ($prefix < 0 || $prefix > $totalBits) {
        return false;
    }

    $wholeBytes = intdiv($prefix, 8);
    $remainingBits = $prefix % 8;
    if ($wholeBytes > 0 && substr($ipBytes, 0, $wholeBytes) !== substr($networkBytes, 0, $wholeBytes)) {
        return false;
    }
    if ($remainingBits === 0) {
        return true;
    }

    $mask = (0xFF << (8 - $remainingBits)) & 0xFF;
    return (ord($ipBytes[$wholeBytes]) & $mask) === (ord($networkBytes[$wholeBytes]) & $mask);
}

/** @param array<int,string> $entries */
function immution_is_whitelisted(string $ip, array $entries): bool
{
    foreach ($entries as $entry) {
        if (!is_string($entry)) {
            continue;
        }
        if ($ip === $entry || (strpos($entry, '/') !== false && immution_ip_in_cidr($ip, $entry))) {
            return true;
        }
    }
    return false;
}

/** @param array<int,string> $patterns */
function immution_is_excluded_path(array $patterns): bool
{
    $uri = $_SERVER['REQUEST_URI'] ?? '/';
    $path = parse_url($uri, PHP_URL_PATH) ?: '/';
    foreach ($patterns as $pattern) {
        if (is_string($pattern) && @preg_match($pattern, $path) === 1) {
            return true;
        }
    }
    return false;
}

/** @return array<string,mixed>|null */
function immution_load_state(string $ip, string $runtimeDir)
{
    $path = rtrim($runtimeDir, '/') . '/' . immution_ip_filename($ip);
    if (!is_file($path) || !is_readable($path)) {
        return null;
    }
    $content = @file_get_contents($path);
    if ($content === false) {
        return null;
    }
    $data = json_decode($content, true);
    return is_array($data) ? $data : null;
}

function immution_bounded_header(string $name, int $limit): string
{
    $value = $_SERVER[$name] ?? '';
    if (!is_string($value)) {
        return '';
    }
    $value = preg_replace('/[\x00-\x1F\x7F]/u', '', $value) ?? '';
    return substr($value, 0, $limit);
}

function immution_csv_safe(string $value): string
{
    // Prevent formula execution when an administrator opens the CSV in a
    // spreadsheet. Request headers and paths are attacker-controlled.
    if ($value !== '' && in_array($value[0], ['=', '+', '-', '@'], true)) {
        return "'" . $value;
    }
    return $value;
}

/** @param array<string,mixed> $data */
function immution_log_event(string $action, string $ip, array $data, array $config)
{
    if (empty($config['log_enabled']) || !is_string($config['log_file'])) {
        return;
    }

    $file = $config['log_file'];
    $newFile = !file_exists($file) || filesize($file) === 0;
    $handle = @fopen($file, 'ab');
    if ($handle === false) {
        return;
    }

    if (flock($handle, LOCK_EX)) {
        if ($newFile) {
            fputcsv($handle, [
                'timestamp', 'action', 'ip', 'host', 'request_uri', 'score',
                'requests', 'errors_404', 'probes', 'user_agent', 'reasons',
            ], ',', '"', '\\');
        }

        $reasons = $data['reasons'] ?? [];
        $reasonText = is_array($reasons) ? implode(' | ', array_slice($reasons, 0, 5)) : '';
        fputcsv($handle, [
            gmdate('c'),
            $action,
            $ip,
            immution_csv_safe(immution_bounded_header('HTTP_HOST', 255)),
            immution_csv_safe(immution_bounded_header('REQUEST_URI', 2048)),
            round((float)($data['score'] ?? 0), 2),
            (int)($data['requests'] ?? 0),
            (int)($data['errors_404'] ?? 0),
            (int)($data['probes'] ?? 0),
            immution_csv_safe(immution_bounded_header('HTTP_USER_AGENT', 512)),
            immution_csv_safe(substr($reasonText, 0, 2000)),
        ], ',', '"', '\\');
        flock($handle, LOCK_UN);
    }
    fclose($handle);
}

function immution_language(): string
{
    $language = $_SERVER['HTTP_ACCEPT_LANGUAGE'] ?? 'en';
    return is_string($language) && stripos($language, 'it') === 0 ? 'it' : 'en';
}

function immution_show_block_page()
{
    http_response_code(403);
    header('Cache-Control: no-store, max-age=0');
    header('Content-Type: text/html; charset=UTF-8');
    header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'");
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: no-referrer');

    $italian = immution_language() === 'it';
    $title = $italian ? 'Accesso temporaneamente limitato' : 'Access temporarily limited';
    $message = $italian
        ? 'Il sistema ha rilevato una sequenza di richieste anomala. Attendi qualche minuto e riprova.'
        : 'The system detected an unusual request pattern. Wait a few minutes and try again.';
    $retry = $italian ? 'Riprova' : 'Try again';
    ?>
<!doctype html>
<html lang="<?= $italian ? 'it' : 'en' ?>">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <title><?= htmlspecialchars($title, ENT_QUOTES, 'UTF-8') ?></title>
    <style>
        :root { color-scheme: dark; }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
               background: #111827; color: #f9fafb; font: 16px/1.55 system-ui, sans-serif; }
        main { width: min(560px, 100%); padding: 36px; border: 1px solid #374151;
               border-radius: 14px; background: #1f2937; }
        h1 { margin: 0 0 12px; font-size: 1.65rem; }
        p { margin: 0 0 24px; color: #d1d5db; }
        a { color: #86efac; font-weight: 700; }
    </style>
</head>
<body>
<main>
    <h1><?= htmlspecialchars($title, ENT_QUOTES, 'UTF-8') ?></h1>
    <p><?= htmlspecialchars($message, ENT_QUOTES, 'UTF-8') ?></p>
    <a href=""><?= htmlspecialchars($retry, ENT_QUOTES, 'UTF-8') ?></a>
</main>
</body>
</html>
    <?php
    exit;
}

$config = immution_config();
if (empty($config['enabled']) || immution_is_excluded_path($config['exclude_paths'])) {
    return;
}

$ip = immution_client_ip();
if ($ip === null || $ip === '::1' || strncmp($ip, '127.', 4) === 0) {
    return;
}
if (immution_is_whitelisted($ip, $config['whitelist'])) {
    return;
}

$state = immution_load_state($ip, (string)$config['runtime_dir']);
if ($state === null || empty($state['banned'])) {
    return;
}

$monitorOnly = $config['mode'] !== 'block';
immution_log_event($monitorOnly ? 'would_block' : 'blocked', $ip, $state, $config);
if ($monitorOnly) {
    return;
}

immution_show_block_page();
