<?php
/** PHP 7.0-compatible smoke tests for the supported request gate. */

declare(strict_types=1);

function immution_test_assert($condition, $message)
{
    if ($condition) {
        return;
    }
    fwrite(STDERR, "FAIL: " . $message . PHP_EOL);
    exit(1);
}

$_SERVER = [
    'REMOTE_ADDR' => '192.0.2.10',
    'HTTP_CF_CONNECTING_IP' => '198.51.100.99',
    'HTTP_X_FORWARDED_FOR' => '203.0.113.99',
    'REQUEST_URI' => '/ordinary-page?value=1',
    'HTTP_HOST' => 'example.test',
    'HTTP_USER_AGENT' => 'Immution compatibility test',
    'HTTP_ACCEPT_LANGUAGE' => 'en',
];

require __DIR__ . '/../src/gate.php';

immution_test_assert(immution_client_ip() === '192.0.2.10', 'forwarding headers must not replace REMOTE_ADDR');
immution_test_assert(immution_ip_filename('2001:db8::1') === '2001_db8__1.json', 'IPv6 state filename');
immution_test_assert(immution_ip_in_cidr('192.0.2.25', '192.0.2.0/24'), 'IPv4 CIDR match');
immution_test_assert(!immution_ip_in_cidr('192.0.3.25', '192.0.2.0/24'), 'IPv4 CIDR mismatch');
immution_test_assert(immution_ip_in_cidr('2001:db8::25', '2001:db8::/32'), 'IPv6 CIDR match');
immution_test_assert(!immution_ip_in_cidr('2001:db9::25', '2001:db8::/32'), 'IPv6 CIDR mismatch');
immution_test_assert(!immution_ip_in_cidr('192.0.2.25', '192.0.2.0/129'), 'invalid CIDR prefix');
immution_test_assert(
    immution_is_whitelisted('2001:db8::25', ['192.0.2.10', '2001:db8::/32']),
    'CIDR whitelist'
);
immution_test_assert(immution_csv_safe('=2+2') === "'=2+2", 'CSV formula prefix');

$logFile = tempnam(sys_get_temp_dir(), 'immution-php-');
immution_test_assert($logFile !== false, 'temporary log creation');
@unlink($logFile);

$_SERVER['HTTP_HOST'] = '=formula.example';
immution_log_event(
    'would_block',
    '192.0.2.10',
    [
        'score' => 55.5,
        'requests' => 4,
        'errors_404' => 3,
        'probes' => 1,
        'reasons' => ['test probe'],
    ],
    [
        'log_enabled' => true,
        'log_file' => $logFile,
    ]
);

$handle = @fopen($logFile, 'rb');
immution_test_assert($handle !== false, 'event log is readable');
$header = fgetcsv($handle);
$row = fgetcsv($handle);
fclose($handle);
@unlink($logFile);

immution_test_assert(is_array($header) && count($header) === 11, 'CSV header');
immution_test_assert(is_array($row) && count($row) === 11, 'CSV event row');
immution_test_assert($row[1] === 'would_block', 'CSV action');
immution_test_assert($row[3] === "'=formula.example", 'attacker-controlled CSV field is neutralized');

fwrite(STDOUT, 'PHP gate smoke test passed on PHP ' . PHP_VERSION . PHP_EOL);
