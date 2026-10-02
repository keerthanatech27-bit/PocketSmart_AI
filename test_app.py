import os
import sys
import unittest
from fastapi.testclient import TestClient

# Ensure app is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app
from models import HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput
from gemini_utils import get_home_recommendations, get_party_recommendations, get_jewelry_recommendations

class TestPocketSmartAI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_username = "testuser_autogen"
        cls.test_password = "SecurePassword123!"
        cls.test_email = "testuser@example.com"

    def test_01_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PocketSmart", response.text)
        self.assertIn("AI-Powered Budget Planning", response.text)

    def test_02_registration_and_login(self):
        # Register
        reg_payload = {
            "username": self.test_username,
            "email": self.test_email,
            "password": self.test_password,
            "full_name": "Test User"
        }
        res_reg = self.client.post("/register", json=reg_payload)
        self.assertIn(res_reg.status_code, [200, 400]) # 400 if already created in persistent db

        # Login
        login_payload = {
            "username": self.test_username,
            "password": self.test_password
        }
        res_login = self.client.post("/login", json=login_payload)
        self.assertEqual(res_login.status_code, 200)
        token_data = res_login.json()
        self.assertIn("access_token", token_data)
        
        # Save token for auth tests
        self.__class__.token = token_data["access_token"]
        self.__class__.auth_headers = {"Authorization": f"Bearer {self.token}"}

    def test_03_dashboard_authenticated(self):
        res = self.client.get("/dashboard", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("Home Budget Planner", res.text)
        self.assertIn("Party Budget Planner", res.text)
        self.assertIn("Jewelry Budget Planner", res.text)

    def test_04_home_planner_endpoint(self):
        payload = {
            "total_budget": 10000.0,
            "num_lights": 4,
            "num_fans": 2,
            "num_furniture": 2,
            "num_dining_tables": 1,
            "has_living_room": True,
            "has_kitchen": True,
            "has_bedroom": False,
            "additional_requirements": "Modern minimalist"
        }
        res = self.client.post("/home-budget", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_budget", data)
        self.assertIn("budget_breakdown", data)
        self.assertIn("calculation_table", data)
        self.assertTrue(len(data["budget_breakdown"]) > 0)
        # Verify shopping links
        first_cat = data["budget_breakdown"][0]
        first_item = first_cat["items"][0]
        self.assertIn("shopping_links", first_item)
        self.assertIn("amazon", first_item["shopping_links"])
        self.assertIn("flipkart", first_item["shopping_links"])

    def test_05_party_planner_endpoint(self):
        payload = {
            "total_budget": 5000.0,
            "num_guests": 5,
            "party_type": "Birthday",
            "venue_type": "Home",
            "needs_catering": True,
            "needs_decoration": True,
            "needs_entertainment": True,
            "additional_requirements": "Vegetarian snacks"
        }
        res = self.client.post("/party-budget", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_budget", data)
        self.assertIn("budget_breakdown", data)
        self.assertIn("venue_suggestions", data)

    def test_06_jewelry_planner_endpoint(self):
        data = {
            "total_budget": 3000.0,
            "occasion": "Wedding",
            "preferences": "Traditional gold plated"
        }
        res = self.client.post("/jewelry-budget", data=data, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        json_data = res.json()
        self.assertIn("total_budget", json_data)
        self.assertIn("jewelry_recommendations", json_data)
        first_item = json_data["jewelry_recommendations"][0]
        self.assertIn("shopping_links", first_item)
        self.assertIn("tanishq", first_item["shopping_links"])

    def test_07_recommendation_history_and_details(self):
        res = self.client.get("/recommendation-history", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        history = res.json().get("history", [])
        self.assertTrue(len(history) >= 3)
        
        # Test detail of first recommendation
        rec_id = history[0]["id"]
        res_detail = self.client.get(f"/recommendation-details/{rec_id}", headers=self.auth_headers)
        self.assertEqual(res_detail.status_code, 200)
        detail_data = res_detail.json()
        self.assertEqual(detail_data["id"], rec_id)

    def test_08_session_info(self):
        res = self.client.get("/session-info", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        session_data = res.json()
        self.assertEqual(session_data["username"], self.test_username)

if __name__ == "__main__":
    unittest.main()
