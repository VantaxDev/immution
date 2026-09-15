# Threat model

## In scope

- opportunistic discovery of exposed configuration and backup files;
- repeated 404 scanning and high-confidence probe paths;
- temporary local enforcement before PHP application code executes;
- transparent evidence for every temporary ban.

## Out of scope

- volumetric or network-layer DDoS attacks;
- attacks that never reach Apache;
- static responses that do not invoke PHP;
- compromised local accounts or a compromised `www-data` process;
- identification of every legitimate or malicious bot;
- vulnerability discovery, malware removal or application patching;
- authenticated abuse that resembles normal application traffic.

## Trust boundaries

The effective client address is the first Apache log field and PHP
`REMOTE_ADDR`. Forwarding headers are untrusted unless Apache `mod_remoteip` has
validated the upstream proxy and rewritten the address consistently.

The daemon writes state as the `immution` user to `/run/immution`. PHP reads
that state as a member of the `www-data` group. PHP does not write ban state.

## Failure behaviour

- missing, malformed or unreadable state: allow the request;
- daemon unavailable: no new scoring; existing readable state applies for at most one hour since its last update;
- event log unavailable: enforcement can continue, but the logging error is not
  exposed to the visitor;
- invalid configuration mode: fall back to monitor mode.
