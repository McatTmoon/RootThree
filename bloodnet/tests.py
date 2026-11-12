import json
import uuid

import threading

from django.test import Client, TestCase, TransactionTestCase
from unittest.mock import patch

from .models import BloodRequest, IdempotencyRecord, StockDispatch, DonorInvitation, DonorTrack, CallbackEvent
from .inventory import allocate_inventory_for_request, retry_dispatch, process_stock_arrivals
from .donors import is_donor_eligible, send_donor_invitations, stop_donor_outreach, load_donor_data


class HealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_get_returns_200_and_ok_true(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_health_post_not_allowed(self):
        response = self.client.post("/health")
        self.assertEqual(response.status_code, 405)


class RequestAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.auth_headers = {"HTTP_AUTHORIZATION": "Bearer hospital-token"}
        self.valid_payload = {
            "hospital_id": "H01",
            "blood_group": "O-",
            "product": "red_cells",
            "units": 2,
            "urgency": "critical",
        }

    # 1. Successful creation and persistence
    def test_create_request_success(self):
        key = f"k-{uuid.uuid4().hex}"
        response = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("request_id", data)
        self.assertTrue(data["request_id"].startswith("R-"))
        self.assertEqual(data["status"], "open")
        self.assertEqual(data["needed"], 2)

        # Check DB persistence
        db_req = BloodRequest.objects.get(request_id=data["request_id"])
        self.assertEqual(db_req.hospital_id, "H01")
        self.assertEqual(db_req.blood_group, "O-")
        self.assertEqual(db_req.needed, 2)

        # Check idempotency record
        idem = IdempotencyRecord.objects.get(key=key)
        self.assertEqual(idem.response_code, 201)
        self.assertEqual(idem.request, db_req)

    # 2. Idempotency behavior: repeated submission with same key
    def test_idempotent_replay_same_body(self):
        key = f"k-{uuid.uuid4().hex}"
        r1 = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.auth_headers,
        )
        self.assertEqual(r1.status_code, 201)
        rid1 = r1.json()["request_id"]

        # Second submission: exact same key and body
        r2 = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.auth_headers,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["request_id"], rid1)
        self.assertEqual(BloodRequest.objects.count(), 1)

    # 3. Idempotency behavior: repeated key with different body -> 422
    def test_idempotency_key_reuse_different_body(self):
        key = f"k-{uuid.uuid4().hex}"
        r1 = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.auth_headers,
        )
        self.assertEqual(r1.status_code, 201)

        diff_payload = {**self.valid_payload, "units": 4}
        r2 = self.client.post(
            "/requests",
            data=json.dumps(diff_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.auth_headers,
        )
        self.assertEqual(r2.status_code, 422)
        self.assertEqual(r2.json().get("error", {}).get("code"), "idempotency_key_reuse")

    # 4. Authentication tests
    def test_create_request_missing_auth(self):
        key = f"k-{uuid.uuid4().hex}"
        response = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("error", {}).get("code"), "unauthorized")

    def test_create_request_invalid_auth(self):
        key = f"k-{uuid.uuid4().hex}"
        response = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )
        self.assertEqual(response.status_code, 401)

    # 5. Missing / invalid Idempotency-Key
    def test_create_request_missing_idempotency_key(self):
        response = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error", {}).get("code"), "missing_idempotency_key")

    # 6. Input validation tests
    def test_create_request_invalid_json(self):
        response = self.client.post(
            "/requests",
            data="not json",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_missing_required_field(self):
        bad_payload = dict(hospital_id="H01", blood_group="O-", product="red_cells", units=2)
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error", {}).get("code"), "validation_error")

    def test_create_request_unexpected_fields(self):
        bad_payload = {**self.valid_payload, "extra_field": "disallowed"}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_invalid_blood_group(self):
        bad_payload = {**self.valid_payload, "blood_group": "Z+"}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_invalid_product(self):
        bad_payload = {**self.valid_payload, "product": "whole_blood"}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_invalid_urgency(self):
        bad_payload = {**self.valid_payload, "urgency": "super_urgent"}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_negative_units(self):
        bad_payload = {**self.valid_payload, "units": -1}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_zero_units(self):
        bad_payload = {**self.valid_payload, "units": 0}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_excessive_units(self):
        bad_payload = {**self.valid_payload, "units": 25}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_request_unknown_hospital(self):
        bad_payload = {**self.valid_payload, "hospital_id": "H98"}
        response = self.client.post(
            "/requests",
            data=json.dumps(bad_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("error", {}).get("code"), "unknown_hospital")

    def test_create_request_sim_time_header(self):
        response = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            HTTP_X_SIM_TIME="145.25",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        rid = response.json()["request_id"]
        db_req = BloodRequest.objects.get(request_id=rid)
        self.assertAlmostEqual(db_req.created_sim_min, 145.25)

    # 7. Retrieval tests GET /requests/{id}
    def test_get_request_success(self):
        create_res = self.client.post(
            "/requests",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid.uuid4().hex}",
            **self.auth_headers,
        )
        rid = create_res.json()["request_id"]

        get_res = self.client.get(f"/requests/{rid}", **self.auth_headers)
        self.assertEqual(get_res.status_code, 200)
        data = get_res.json()
        expected_keys = ("request_id", "status", "needed", "confirmed", "en_route", "arrived", "fulfilled")
        for key in expected_keys:
            self.assertIn(key, data)
        self.assertEqual(data["request_id"], rid)
        self.assertEqual(data["hospital_id"], "H01")
        self.assertEqual(data["blood_group"], "O-")
        self.assertEqual(data["needed"], 2)
        self.assertEqual(data["status"], "open")

    def test_get_request_not_found(self):
        response = self.client.get("/requests/nope", **self.auth_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("error", {}).get("code"), "not_found")

    def test_get_request_missing_auth(self):
        response = self.client.get("/requests/R-123456789012")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("error", {}).get("code"), "unauthorized")


class ConcurrentIdempotencyTests(TransactionTestCase):
    def test_twenty_concurrent_requests_same_key(self):
        key = f"conc-{uuid.uuid4().hex}"
        payload = {
            "hospital_id": "H01",
            "blood_group": "O-",
            "product": "red_cells",
            "units": 2,
            "urgency": "critical",
        }
        results = []

        def worker():
            c = Client()
            res = c.post(
                "/requests",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=key,
                HTTP_AUTHORIZATION="Bearer hospital-token",
            )
            results.append((res.status_code, res.json().get("request_id")))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 created (201) and 19 replayed (200)
        status_201_count = sum(1 for status, _ in results if status == 201)
        status_200_count = sum(1 for status, _ in results if status == 200)
        request_ids = {rid for _, rid in results if rid}

        self.assertEqual(status_201_count, 1)
        self.assertEqual(status_200_count, 19)
        self.assertEqual(len(request_ids), 1)
        self.assertEqual(BloodRequest.objects.count(), 1)


class MockedInventoryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hospital_auth = {"HTTP_AUTHORIZATION": "Bearer hospital-token"}
        self.coordinator_auth = {"HTTP_AUTHORIZATION": "Bearer coordinator-token"}

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_partial_allocation(self, mock_dispatch, mock_fetch):
        # 5 units needed, but inventory only has 2 units
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 150.0}
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-p1", "units": 2, "eta_sim_min": 25.0})

        req = BloodRequest.objects.create(
            request_id="R-PARTIAL-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="urgent",
            needed=5,
            status="open",
        )

        res = allocate_inventory_for_request(req.request_id)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "dispatched")
        self.assertEqual(res[0]["units"], 2)

        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 2)
        self.assertEqual(req.shortage, 3)
        self.assertEqual(req.dispatches.count(), 1)
        disp = req.dispatches.first()
        self.assertEqual(disp.units, 2)
        self.assertEqual(disp.status, "dispatched")
        self.assertEqual(disp.eta_sim_min, 25.0)

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_compatibility_filtering(self, mock_dispatch, mock_fetch):
        # O- recipient can ONLY receive O- red cells (O+ and A- must be excluded)
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O+", "product": "red_cells", "units": 10, "expires_sim_min": 100.0},
            {"center_id": "MC2", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 100.0},
            {"center_id": "MC3", "blood_group": "A-", "product": "red_cells", "units": 5, "expires_sim_min": 100.0},
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-c1", "units": 2, "eta_sim_min": 30.0})

        req = BloodRequest.objects.create(
            request_id="R-COMPAT-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        res = allocate_inventory_for_request(req.request_id)
        self.assertEqual(len(res), 1)

        # Ensure dispatch was called with compatible O- only
        disp_call_body = mock_dispatch.call_args[0][1]
        self.assertEqual(disp_call_body["center_id"], "MC2")
        self.assertEqual(disp_call_body["blood_group"], "O-")

        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 2)
        self.assertEqual(req.shortage, 0)

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_expiration_filtering(self, mock_dispatch, mock_fetch):
        # Current sim_time = 100.0; batch with expiry 80.0 is expired and must be skipped
        mock_fetch.return_value = (100.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 80.0},
            {"center_id": "MC2", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 150.0},
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-e1", "units": 2, "eta_sim_min": 125.0})

        req = BloodRequest.objects.create(
            request_id="R-EXPIRY-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="planned",
            needed=2,
            status="open",
        )

        res = allocate_inventory_for_request(req.request_id)
        self.assertEqual(len(res), 1)

        disp_call_body = mock_dispatch.call_args[0][1]
        self.assertEqual(disp_call_body["center_id"], "MC2")

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_fefo_ordering(self, mock_dispatch, mock_fetch):
        # Two compatible batches: MC1 expires at 300.0, MC2 expires at 120.0
        # FEFO requires MC2 (earlier expiry) to be chosen first
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 300.0},
            {"center_id": "MC2", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 120.0},
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-f1", "units": 2, "eta_sim_min": 20.0})

        req = BloodRequest.objects.create(
            request_id="R-FEFO-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="urgent",
            needed=2,
            status="open",
        )

        res = allocate_inventory_for_request(req.request_id)
        self.assertEqual(len(res), 1)

        disp_call_body = mock_dispatch.call_args[0][1]
        self.assertEqual(disp_call_body["center_id"], "MC2")

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_competing_requests_insufficient_stock(self, mock_dispatch, mock_fetch):
        # Two competing requests for the same stock
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 200.0}
        ])

        req1 = BloodRequest.objects.create(
            request_id="R-COMP-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )
        req2 = BloodRequest.objects.create(
            request_id="R-COMP-2",
            hospital_id="H02",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        # First request succeeds
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-1", "units": 2, "eta_sim_min": 25.0})
        res1 = allocate_inventory_for_request(req1.request_id)
        self.assertEqual(res1[0]["status"], "dispatched")

        # Second request gets 409 insufficient stock from service
        mock_dispatch.return_value = (409, {"error": {"code": "insufficient_stock", "message": "available=0"}})
        res2 = allocate_inventory_for_request(req2.request_id)
        self.assertEqual(res2[0]["status"], "failed")
        self.assertEqual(res2[0]["code"], 409)

        req2.refresh_from_db()
        self.assertEqual(req2.stock_inflight, 0)
        self.assertEqual(req2.shortage, 2)
        self.assertEqual(req2.dispatches.first().status, "failed")

    @patch("bloodnet.inventory.dispatch_http_call")
    def test_retry_after_lost_response_no_double_counting(self, mock_dispatch):
        req = BloodRequest.objects.create(
            request_id="R-RETRY-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        # Pre-record a pending dispatch (simulating lost response on first attempt)
        disp = StockDispatch.objects.create(
            dispatch_id="dsp-lost-123",
            request=req,
            center_id="MC1",
            blood_group="O-",
            product="red_cells",
            units=2,
            hospital_id="H01",
            recipient_blood_group="O-",
            status="pending",
        )

        # Server returns 200 (idempotent replay of previously received dispatch)
        mock_dispatch.return_value = (200, {"dispatch_id": "dsp-lost-123", "units": 2, "eta_sim_min": 35.0})

        ok, _ = retry_dispatch("dsp-lost-123")
        self.assertTrue(ok)

        disp.refresh_from_db()
        self.assertEqual(disp.status, "dispatched")
        self.assertEqual(disp.eta_sim_min, 35.0)

        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 2)
        self.assertEqual(req.shortage, 0)

        # Calling retry again must be a no-op without double-counting
        ok2, msg2 = retry_dispatch("dsp-lost-123")
        self.assertTrue(ok2)
        self.assertEqual(msg2, "Already dispatched")

        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 2)

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_approval_rule_no_allocation_when_pending_review(self, mock_dispatch, mock_fetch):
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 200.0}
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-appr-1", "units": 2, "eta_sim_min": 25.0})

        req = BloodRequest.objects.create(
            request_id="R-APPR-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="urgent",
            needed=2,
            status="pending_review",
        )

        # 1. While in pending_review, allocation must NOT take place
        res = allocate_inventory_for_request(req.request_id)
        self.assertEqual(res, [])
        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 0)
        self.assertEqual(req.dispatches.count(), 0)

        # 2. Approve via POST /requests/{id}/approve
        approve_res = self.client.post(
            f"/requests/{req.request_id}/approve",
            **self.coordinator_auth,
        )
        self.assertEqual(approve_res.status_code, 200)

        req.refresh_from_db()
        self.assertIn(req.status, ("open", "mobilizing"))
        self.assertEqual(req.stock_inflight, 2)
        self.assertEqual(req.shortage, 0)

    @patch("bloodnet.inventory.fetch_live_inventory")
    @patch("bloodnet.inventory.dispatch_http_call")
    def test_idempotent_replay_does_not_duplicate_dispatch(self, mock_dispatch, mock_fetch):
        mock_fetch.return_value = (0.0, [
            {"center_id": "MC1", "blood_group": "O-", "product": "red_cells", "units": 2, "expires_sim_min": 200.0}
        ])
        mock_dispatch.return_value = (201, {"dispatch_id": "dsp-idem-1", "units": 2, "eta_sim_min": 25.0})

        key = f"k-idem-{uuid.uuid4().hex}"
        payload = {
            "hospital_id": "H01",
            "blood_group": "O-",
            "product": "red_cells",
            "units": 2,
            "urgency": "critical",
        }

        # First request creation triggers allocation
        r1 = self.client.post(
            "/requests",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.hospital_auth,
        )
        self.assertEqual(r1.status_code, 201)
        rid = r1.json()["request_id"]

        req = BloodRequest.objects.get(request_id=rid)
        self.assertEqual(req.dispatches.count(), 1)
        self.assertEqual(mock_dispatch.call_count, 1)

        # Replaying identical request with same key
        r2 = self.client.post(
            "/requests",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.hospital_auth,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["request_id"], rid)

        # Confirm dispatch was NOT called again
        self.assertEqual(mock_dispatch.call_count, 1)
        self.assertEqual(req.dispatches.count(), 1)


class LocalInventoryIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import types
        from harness import world, physics, inventory_service
        from harness.common import VClock
        from harness.simconfig import RULES_V1

        cls.port = 9377
        cls.W = world.build_world("participant_kit")
        cls.clock = VClock(240.0)
        cls.dm = types.SimpleNamespace(
            S=world.load_state(cls.W, "participant_kit"),
            lock=threading.Lock(),
            truth={},
            donations=[],
        )
        cls.inv = inventory_service.Inventory(cls.W, cls.dm, cls.clock, physics.Rules(RULES_V1), practice=True)
        cls.inv.new_day(0)
        cls.server = inventory_service.serve(cls.inv, cls.port)
        cls.inventory_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def test_actual_local_service_partial_allocation(self):
        # In live inventory, total available O+ and A+ red_cells across centers is 5 units.
        # Hospital H07 requests 8 units of A+ red_cells -> exactly 5 units can be dispatched by the real local service
        req = BloodRequest.objects.create(
            request_id="R-REAL-INV-1",
            hospital_id="H07",
            blood_group="A+",
            product="red_cells",
            urgency="urgent",
            needed=8,
            status="open",
        )

        res = allocate_inventory_for_request(req.request_id, inventory_url=self.inventory_url)
        self.assertTrue(len(res) > 0)
        total_dispatched = sum(d["units"] for d in res if d["status"] == "dispatched")
        self.assertEqual(total_dispatched, 5)
        for d in res:
            self.assertEqual(d["status"], "dispatched")
            self.assertIsNotNone(d["eta_sim_min"])

        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 5)
        self.assertEqual(req.shortage, 3)  # 8 needed - 5 inflight = 3 shortage remaining

        # Second allocation attempt: all compatible stock was consumed by the real service -> 0 available
        res2 = allocate_inventory_for_request(req.request_id, inventory_url=self.inventory_url)
        self.assertEqual(len(res2), 0)
        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 5)
        self.assertEqual(req.shortage, 3)


class DonorOutreachAndCallbackTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hospital_auth = {"HTTP_AUTHORIZATION": "Bearer hospital-token"}
        self.coordinator_auth = {"HTTP_AUTHORIZATION": "Bearer coordinator-token"}
        load_donor_data()

    @patch("bloodnet.donors.post_gateway_message")
    def test_shortage_triggers_invitations(self, mock_gw):
        mock_gw.return_value = (202, {"notification_id": "nt-1", "status": "accepted"})

        req = BloodRequest.objects.create(
            request_id="R-DONOR-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="urgent",
            needed=3,
            status="open",
        )

        sent = send_donor_invitations(req.request_id, max_cap=5)
        self.assertTrue(len(sent) > 0)
        self.assertTrue(mock_gw.called)

        invs = DonorInvitation.objects.filter(request=req)
        self.assertEqual(invs.count(), len(sent))
        tracks = DonorTrack.objects.filter(request=req)
        self.assertEqual(tracks.count(), len(sent))
        for t in tracks:
            self.assertEqual(t.state, "invited")

    def test_donor_deferral_exclusion(self):
        from .donors import _DEFER_CACHE, _DONORS_CACHE
        deferred_dids = list(_DEFER_CACHE.keys())
        self.assertTrue(len(deferred_dids) > 0)

        deferred_did = deferred_dids[0]
        donor_profile = next(d for d in _DONORS_CACHE if d["donor_id"] == deferred_did)

        eligible_at_start = is_donor_eligible(donor_profile, "red_cells", sim_time_min=0.0)
        self.assertFalse(eligible_at_start)

    def test_duplicate_callbacks_deduplicated(self):
        req = BloodRequest.objects.create(
            request_id="R-DUP-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )
        ev_id = f"ev-{uuid.uuid4().hex}"
        payload = {
            "event_id": ev_id,
            "request_id": req.request_id,
            "donor_id": "D00001",
            "event": "en_route",
            "sim_time": 10.0,
        }

        # First callback
        r1 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.en_route, 1)

        # Duplicate callback with exact same event_id
        r2 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.en_route, 1)

        self.assertEqual(CallbackEvent.objects.filter(event_id=ev_id).count(), 1)

    def test_late_out_of_order_callbacks_do_not_move_backward(self):
        req = BloodRequest.objects.create(
            request_id="R-OOO-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )
        donor_id = "D00002"

        # 1. Arrived event arrives first (out-of-order)
        arr_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "request_id": req.request_id,
            "donor_id": donor_id,
            "event": "arrived",
            "sim_time": 25.0,
        }
        r1 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(arr_payload),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200)

        track = DonorTrack.objects.get(request=req, donor_id=donor_id)
        self.assertEqual(track.state, "arrived")
        req.refresh_from_db()
        self.assertEqual(req.arrived, 1)

        # 2. Later, late 'en_route' callback arrives
        en_route_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "request_id": req.request_id,
            "donor_id": donor_id,
            "event": "en_route",
            "sim_time": 15.0,
        }
        r2 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(en_route_payload),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)

        track.refresh_from_db()
        self.assertEqual(track.state, "arrived")

    @patch("bloodnet.callbacks.post_gateway_message")
    def test_acceptance_without_fulfillment(self, mock_gw):
        mock_gw.return_value = (202, {"notification_id": "nt-c", "status": "accepted"})

        req = BloodRequest.objects.create(
            request_id="R-ACCEPT-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        resp_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "notification_id": "nt-acc-1",
            "request_id": req.request_id,
            "donor_id": "D00003",
            "response": "accepted",
            "sim_time": 12.0,
        }

        res = self.client.post(
            "/callbacks/donor-response",
            data=json.dumps(resp_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        req.refresh_from_db()
        self.assertEqual(req.confirmed, 1)
        self.assertEqual(req.fulfilled, 0)
        self.assertEqual(req.shortage, 2)

        track = DonorTrack.objects.get(request=req, donor_id="D00003")
        self.assertEqual(track.state, "accepted")

        self.assertTrue(mock_gw.called)
        call_payload = mock_gw.call_args[0][0]
        self.assertEqual(call_payload["template"], "confirmed")
        self.assertEqual(call_payload["donor_id"], "D00003")

    def test_valid_donation_counted_once(self):
        req = BloodRequest.objects.create(
            request_id="R-DONATE-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        donated_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "request_id": req.request_id,
            "donor_id": "D00004",
            "event": "donated",
            "sim_time": 60.0,
        }

        res1 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(donated_payload),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 200)

        req.refresh_from_db()
        self.assertEqual(req.fulfilled, 1)

        track = DonorTrack.objects.get(request=req, donor_id="D00004")
        self.assertEqual(track.state, "donated")
        self.assertEqual(track.donated_sim_min, 60.0)

        # Repeated donated event with new event_id for the same donor
        repeat_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "request_id": req.request_id,
            "donor_id": "D00004",
            "event": "donated",
            "sim_time": 61.0,
        }
        res2 = self.client.post(
            "/callbacks/donor-progress",
            data=json.dumps(repeat_payload),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 200)

        req.refresh_from_db()
        self.assertEqual(req.fulfilled, 1)

    @patch("bloodnet.views.stop_donor_outreach")
    def test_cancellation_stops_outreach(self, mock_stop):
        req = BloodRequest.objects.create(
            request_id="R-CANCEL-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="critical",
            needed=2,
            status="open",
        )

        res = self.client.post(f"/requests/{req.request_id}/cancel", **self.hospital_auth)
        self.assertEqual(res.status_code, 200)

        req.refresh_from_db()
        self.assertEqual(req.status, "cancelled")
        self.assertTrue(mock_stop.called)

        invs = send_donor_invitations(req.request_id)
        self.assertEqual(invs, [])

    def test_stock_arrival_reduces_inflight_and_fulfills(self):
        req = BloodRequest.objects.create(
            request_id="R-STOCK-ARRIVE-1",
            hospital_id="H01",
            blood_group="O-",
            product="red_cells",
            urgency="urgent",
            needed=2,
            status="mobilizing",
            stock_inflight=2,
            fulfilled=0,
        )

        disp = StockDispatch.objects.create(
            dispatch_id="dsp-arr-1",
            request=req,
            center_id="MC1",
            blood_group="O-",
            product="red_cells",
            units=2,
            hospital_id="H01",
            recipient_blood_group="O-",
            status="dispatched",
            eta_sim_min=30.0,
        )

        # At sim_time = 20.0: stock has not arrived yet
        count1 = process_stock_arrivals(sim_time=20.0)
        self.assertEqual(count1, 0)
        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 2)
        self.assertEqual(req.fulfilled, 0)

        # A callback arrives with sim_time = 35.0 (after ETA 30.0)
        cb_payload = {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "notification_id": "nt-dummy",
            "request_id": req.request_id,
            "donor_id": "D00005",
            "status": "delivered",
            "sim_time": 35.0,
        }
        self.client.post(
            "/callbacks/gateway-status",
            data=json.dumps(cb_payload),
            content_type="application/json",
        )

        # Stock is now arrived!
        req.refresh_from_db()
        self.assertEqual(req.stock_inflight, 0)
        self.assertEqual(req.fulfilled, 2)
        self.assertEqual(req.status, "fulfilled")
        disp.refresh_from_db()
        self.assertEqual(disp.status, "delivered")

