import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from route_mutation import RouteMutationDetector, _extract_route


class RouteMutationTests(unittest.TestCase):
    def setUp(self):
        self.detector = RouteMutationDetector()

    def add(self, path, t, ip='192.0.2.12', scope='vhost-a.log',
            method='POST', size=4583, status=200):
        return self.detector.observe(ip, scope, method, path, status, size, t)

    def test_sample_wp_batch_scan(self):
        # 20 POST in 76 seconds: 18*4583, plus 4599 and 4560.
        routes = [
            '/?rest_route=%2Fbatch%2Fv1',
            '/?rest_route=/batch%2Fv1',
            '/?rest_route=/batch/v1',
            '/?rest_route=/./batch/v1',
        ]
        offsets = [0, 1, 2, 11, 17, 18, 19, 28, 33, 34,
                   35, 43, 49, 50, 52, 60, 66, 67, 68, 76]
        hits = []
        for i, seconds in enumerate(offsets):
            size = 4599 if i == 11 else (4560 if i == 19 else 4583)
            result = self.add(routes[i % 4], seconds, size=size)
            if result:
                hits.append(result)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].route, '/batch/v1')
        self.assertGreaterEqual(hits[0].consistency, 0.85)
        self.assertGreaterEqual(hits[0].suspicious_variants, 2)

    def test_normal_tracking_query_never_starts_bucket(self):
        for i in range(100):
            self.assertIsNone(self.add('/?utm_source=ads' + str(i), i))
        self.assertEqual(len(self.detector._buckets), 0)

    def test_legitimate_single_escaped_variant(self):
        for i in range(50):
            self.assertIsNone(self.add('/?rest_route=%2Fbatch%2Fv1', i))

    def test_response_sizes_vary(self):
        variants = [
            '/?rest_route=%2Fbatch%2Fv1',
            '/?rest_route=/batch%2Fv1',
            '/?rest_route=/batch/v1',
            '/?rest_route=/./batch/v1',
        ]
        for i in range(20):
            self.assertIsNone(self.add(variants[i % 4], i, size=1000 + i))

    def test_isolated_by_ip_scope_method(self):
        variants = ['/?rest_route=%2Fbatch%2Fv1',
                    '/?rest_route=/batch%2Fv1',
                    '/?rest_route=/batch/v1',
                    '/?rest_route=/./batch/v1']
        for i in range(11):
            self.assertIsNone(self.add(variants[i % 4], i))
        self.assertIsNone(self.add(variants[3], 12, ip='192.0.2.13'))
        self.assertIsNone(self.add(variants[3], 12, scope='vhost-b.log'))
        self.assertIsNone(self.add(variants[3], 12, method='GET'))

    def test_200_only(self):
        variants = ['/?rest_route=%2Fbatch%2Fv1',
                    '/?rest_route=/batch%2Fv1',
                    '/?rest_route=/batch/v1',
                    '/?rest_route=/./batch/v1']
        for i in range(40):
            self.assertIsNone(self.add(variants[i % 4], i, status=404))
        self.assertEqual(len(self.detector._buckets), 0)

    def test_old_events_expire(self):
        variants = ['/?rest_route=%2Fbatch%2Fv1',
                    '/?rest_route=/batch%2Fv1',
                    '/?rest_route=/batch/v1',
                    '/?rest_route=/./batch/v1']
        for i in range(6):
            self.assertIsNone(self.add(variants[i % 4], i))
        for i in range(6):
            self.assertIsNone(self.add(variants[i % 4], 300 + i))

    def test_dont_double_decode(self):
        self.assertNotEqual(_extract_route('/?rest_route=%252Fbatch%252Fv1')[0],
                            _extract_route('/?rest_route=%2Fbatch%2Fv1')[0])

    def test_unrelated_query_values_are_not_route_variants(self):
        variants = ['/?rest_route=%2Fbatch%2Fv1&session=' + str(i)
                    for i in range(20)]
        for i, path in enumerate(variants):
            self.assertIsNone(self.add(path, i))

    def test_oversized_route_is_rejected(self):
        self.assertIsNone(_extract_route('/?rest_route=%2F' + 'a' * 300))

    def test_memory_bound(self):
        detector = RouteMutationDetector(max_keys=5)
        for i in range(100):
            detector.observe('192.0.2.' + str(i + 1), 'a', 'GET',
                             '/%2Ftest', 200, 5000, float(i))
        self.assertLessEqual(len(detector._buckets), 5)


if __name__ == '__main__':
    unittest.main()
