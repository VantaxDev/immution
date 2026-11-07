<?php
/** Synthetic CLI request. All supplied paths must be within a TemporaryDirectory. */
declare(strict_types=1);
$_SERVER = json_decode(file_get_contents($argv[2]), true);
http_response_code(200);
require $argv[1];
echo json_encode([
    'application_reached' => true,
    'status' => http_response_code(),
    'mode' => immution_config()['mode'],
    'client_ip' => immution_client_ip(),
]) . PHP_EOL;
