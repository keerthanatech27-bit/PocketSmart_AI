import os
import json
import re
import urllib.parse
from typing import Optional, Dict, Any, List
from PIL import Image
import google.generativeai as genai
from models import HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput

# Initialize Gemini model if API key is provided
API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
model = None
vision_model = None

if API_KEY and API_KEY.strip() and API_KEY != "your_gemini_api_key_here":
    try:
        genai.configure(api_key=API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        vision_model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        print(f"Warning: Could not initialize Gemini model: {e}")

def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extract and parse JSON safely from Gemini model response."""
    if not text:
        return {}
    
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    
    # Try finding markdown code block ```json ... ```
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        clean_text = match.group(1).strip()
        try:
            return json.loads(clean_text)
        except Exception:
            pass

    # Try finding first { to last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
            
    raise ValueError(f"Could not parse valid JSON from AI output: {text[:200]}...")

def get_home_recommendations(budget_input: HomeBudgetInput) -> dict:
    """Generate home interior recommendations within budget in INR for Indian market"""
    global model
    
    rooms_list = []
    if budget_input.has_living_room:
        rooms_list.append("Living Room")
    if budget_input.has_kitchen:
        rooms_list.append("Kitchen")
    if budget_input.has_bedroom:
        rooms_list.append("Bedroom")
    rooms_str = ", ".join(rooms_list) if rooms_list else "General Home"

    if model:
        try:
            prompt = f"""
I need interior design product recommendations for a home in India with a total budget of ₹{budget_input.total_budget:.2f}.
Requirements:
- {budget_input.num_lights} lights/lighting fixtures
- {budget_input.num_fans} ceiling fans
- {budget_input.num_furniture} furniture pieces
- {budget_input.num_dining_tables} dining tables

Additional rooms to consider:
{("- Living Room" if budget_input.has_living_room else "")}
{("- Kitchen" if budget_input.has_kitchen else "")}
{("- Bedroom" if budget_input.has_bedroom else "")}

Additional requirements: {budget_input.additional_requirements or "None"}

Please provide a detailed budget breakdown with product recommendations **available in India**.
Use **Indian brands and pricing**. Include **search terms** suitable for Indian shopping platforms.

Format your response as JSON with the following structure:
{{
  "total_budget": {budget_input.total_budget:.2f},
  "budget_breakdown": [
    {{
      "category": "lighting",
      "allocation": 0.0,
      "items": [
        {{
          "name": "LED Bulb (Warm White)",
          "description": "Energy-efficient LED bulbs for ambient lighting.",
          "estimated_price": 0.0,
          "quantity": 0,
          "search_terms": "Philips 10W LED bulb pack"
        }}
      ]
    }}
  ],
  "calculation_table": [
    {{
      "category": "lighting",
      "items_count": 0,
      "total_cost": 0.0,
      "percentage_of_budget": 0.0
    }}
  ],
  "remaining_budget": 0.0,
  "additional_suggestions": [
    "Consider purchasing during festive sales for extra discounts.",
    "Prioritize essential fixtures first."
  ]
}}

Ensure total costs stay within budget. Include search terms for each item to find on shopping websites like Flipkart, Amazon India, IKEA India, Myntra, and Ajio.
"""
            response = model.generate_content(prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini API home generation encountered error: {e}. Using intelligent fallback engine.")
            result = _generate_fallback_home_recommendations(budget_input)
    else:
        result = _generate_fallback_home_recommendations(budget_input)

    # Attach shopping links to all items
    for category in result.get("budget_breakdown", []):
        for item in category.get("items", []):
            search_terms = item.get("search_terms") or item.get("name", "")
            if search_terms:
                encoded_term = urllib.parse.quote_plus(search_terms)
                item["shopping_links"] = {
                    "amazon": f"https://www.amazon.in/s?k={encoded_term}",
                    "flipkart": f"https://www.flipkart.com/search?q={encoded_term}",
                    "ikea": f"https://www.ikea.com/in/en/search/?q={encoded_term}",
                    "myntra": f"https://www.myntra.com/search?q={encoded_term}",
                    "ajio": f"https://www.ajio.com/search/?text={encoded_term}"
                }
                
    return result

def _generate_fallback_home_recommendations(budget_input: HomeBudgetInput) -> dict:
    """Fallback generator providing structured home interior recommendations"""
    total = budget_input.total_budget
    breakdown = []
    calc_table = []
    spent = 0.0

    # 1. Lighting
    if budget_input.num_lights > 0:
        unit_price = min(total * 0.15 / max(1, budget_input.num_lights), 500.0)
        cost = unit_price * budget_input.num_lights
        spent += cost
        breakdown.append({
            "category": "lighting",
            "allocation": round(cost, 2),
            "items": [{
                "name": "Smart LED Warm White Bulbs",
                "description": "Energy-efficient LED illumination with durable lifespan and warm mood tones.",
                "estimated_price": round(unit_price, 2),
                "quantity": budget_input.num_lights,
                "search_terms": "Philips 12W LED Warm White bulb"
            }]
        })
        calc_table.append({
            "category": "lighting",
            "items_count": budget_input.num_lights,
            "total_cost": round(cost, 2),
            "percentage_of_budget": round((cost / total) * 100, 1) if total else 0
        })

    # 2. Ceiling Fans
    if budget_input.num_fans > 0:
        unit_price = min(total * 0.25 / max(1, budget_input.num_fans), 2200.0)
        cost = unit_price * budget_input.num_fans
        spent += cost
        breakdown.append({
            "category": "ceiling_fans",
            "allocation": round(cost, 2),
            "items": [{
                "name": "High-Speed Energy Saver Ceiling Fan",
                "description": "Havells or Crompton 1200mm aerodynamically designed silent ceiling fan.",
                "estimated_price": round(unit_price, 2),
                "quantity": budget_input.num_fans,
                "search_terms": "Havells 1200mm high speed ceiling fan"
            }]
        })
        calc_table.append({
            "category": "ceiling_fans",
            "items_count": budget_input.num_fans,
            "total_cost": round(cost, 2),
            "percentage_of_budget": round((cost / total) * 100, 1) if total else 0
        })

    # 3. Furniture
    if budget_input.num_furniture > 0:
        unit_price = min(total * 0.35 / max(1, budget_input.num_furniture), 4500.0)
        cost = unit_price * budget_input.num_furniture
        spent += cost
        breakdown.append({
            "category": "furniture",
            "allocation": round(cost, 2),
            "items": [{
                "name": "Ergonomic Lounge Chairs / Accent Table",
                "description": "Comfortable, modern living room accent furniture piece with sturdy build.",
                "estimated_price": round(unit_price, 2),
                "quantity": budget_input.num_furniture,
                "search_terms": "IKEA modern wooden accent chair"
            }]
        })
        calc_table.append({
            "category": "furniture",
            "items_count": budget_input.num_furniture,
            "total_cost": round(cost, 2),
            "percentage_of_budget": round((cost / total) * 100, 1) if total else 0
        })

    # 4. Dining Tables
    if budget_input.num_dining_tables > 0:
        unit_price = min(total * 0.20 / max(1, budget_input.num_dining_tables), 6000.0)
        cost = unit_price * budget_input.num_dining_tables
        spent += cost
        breakdown.append({
            "category": "dining",
            "allocation": round(cost, 2),
            "items": [{
                "name": "Compact 4-Seater Wooden Dining Set",
                "description": "Space-saving engineered wood dining set with easy-wipe finish.",
                "estimated_price": round(unit_price, 2),
                "quantity": budget_input.num_dining_tables,
                "search_terms": "Engineered wood compact dining table 4 seater"
            }]
        })
        calc_table.append({
            "category": "dining",
            "items_count": budget_input.num_dining_tables,
            "total_cost": round(cost, 2),
            "percentage_of_budget": round((cost / total) * 100, 1) if total else 0
        })

    if not breakdown:
        # Default fallback items if no specific quantities were specified
        breakdown = [
            {
                "category": "decor_and_lighting",
                "allocation": round(total * 0.6, 2),
                "items": [
                    {
                        "name": "Modern Ambient Floor Lamp & LED Kit",
                        "description": "Warm living room corner standing lamp with energy-saving LED lighting.",
                        "estimated_price": round(total * 0.3, 2),
                        "quantity": 1,
                        "search_terms": "Modern standing floor lamp for living room"
                    },
                    {
                        "name": "Geometric Wall Art & Accent Mirror",
                        "description": "Set of 3 minimalist wall frames with reflective accent styling.",
                        "estimated_price": round(total * 0.3, 2),
                        "quantity": 1,
                        "search_terms": "IKEA decorative wall art frames set"
                    }
                ]
            }
        ]
        calc_table = [
            {
                "category": "decor_and_lighting",
                "items_count": 2,
                "total_cost": round(total * 0.6, 2),
                "percentage_of_budget": 60.0
            }
        ]
        spent = total * 0.6

    remaining = max(0.0, total - spent)
    return {
        "total_budget": total,
        "budget_breakdown": breakdown,
        "calculation_table": calc_table,
        "remaining_budget": round(remaining, 2),
        "additional_suggestions": [
            "Consider buying matching lighting fixtures in multi-packs for volume discounts on Amazon India.",
            "Opt for modular furniture from IKEA to make space reconfiguration simple.",
            "Reserve remaining budget for wall paints and small indoor planters to elevate aesthetics."
        ]
    }

def get_party_recommendations(budget_input: PartyBudgetInput) -> dict:
    """Generate party planning recommendations within budget in INR for Indian market"""
    global model

    if model:
        try:
            prompt = f"""
I need party planning recommendations for India with a total budget of ₹{budget_input.total_budget:.2f}.

Party details:
- Type: {budget_input.party_type}
- Number of guests: {budget_input.num_guests}
- Venue type: {budget_input.venue_type or "Not specified"}
- Catering needed: {("Yes" if budget_input.needs_catering else "No")}
- Decoration needed: {("Yes" if budget_input.needs_decoration else "No")}
- Entertainment needed: {("Yes" if budget_input.needs_entertainment else "No")}

Additional requirements: {budget_input.additional_requirements or "None"}

Please provide a detailed budget breakdown with specific recommendations available in India using INR prices.
Use Indian brands, services, and typical cost expectations.

Format your response as JSON with the following structure:
{{
  "total_budget": {budget_input.total_budget:.2f},
  "budget_breakdown": [
    {{
      "category": "venue",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Home Venue Setup",
          "description": "Utilizing home or booked hall for event.",
          "estimated_price": 0.0,
          "quantity": 1,
          "search_terms": "party hall booking"
        }}
      ]
    }}
  ],
  "venue_suggestions": [
    {{
      "name": "Community Club / Banquet Hall",
      "type": "Indoor Banquet",
      "capacity": {budget_input.num_guests},
      "estimated_cost": 0.0,
      "search_terms": "party banquet hall near me"
    }}
  ],
  "remaining_budget": 0.0,
  "additional_suggestions": [
    "Order food platters in advance for group discounts on Swiggy/Zomato.",
    "Use DIY balloon decor kits for cost efficiency."
  ]
}}

Ensure all costs are in INR and total does not exceed the given budget.
Provide search terms suitable for Indian websites such as BookMyShow, Swiggy, Flipkart, Amazon, OYO, etc.
"""
            response = model.generate_content(prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini API party generation error: {e}. Using intelligent fallback engine.")
            result = _generate_fallback_party_recommendations(budget_input)
    else:
        result = _generate_fallback_party_recommendations(budget_input)

    # Create INR calculation table
    result["calculation_table_inr"] = []
    categories = {}

    for category in result.get("budget_breakdown", []):
        cat_name = category.get("category", "Misc")
        if cat_name not in categories:
            categories[cat_name] = {
                "category": cat_name,
                "items_count": 0,
                "total_cost": 0.0,
                "percentage_of_budget": 0.0
            }
        for item in category.get("items", []):
            categories[cat_name]["items_count"] += item.get("quantity", 1)
            categories[cat_name]["total_cost"] += float(item.get("estimated_price", 0.0))

    if result.get("total_budget", 0) > 0:
        for cat_data in categories.values():
            cat_data["percentage_of_budget"] = round((cat_data["total_cost"] / result["total_budget"]) * 100, 1)
            result["calculation_table_inr"].append(cat_data)

    # Define relevant shopping platforms for each category
    category_platforms = {
        "venue": ["google", "booking", "makemytrip", "oyorooms", "nobroker"],
        "catering": ["swiggy", "zomato"],
        "food": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
        "drinks": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
        "decoration": ["amazon", "flipkart", "meesho", "myntra"],
        "entertainment": ["bookmyshow", "amazon", "flipkart"],
        "gifts": ["amazon", "flipkart", "myntra", "meesho"],
        "photography": ["google", "amazon", "flipkart"],
        "music": ["amazon", "flipkart", "bookmyshow"],
        "games": ["amazon", "flipkart"],
        "accessories": ["amazon", "flipkart", "myntra", "meesho"],
        "transportation": ["makemytrip", "google"],
        "return_gifts": ["amazon", "flipkart", "myntra", "meesho"],
        "contingency": ["amazon", "flipkart", "google"]
    }
    default_platforms = ["amazon", "flipkart", "google"]

    # Add shopping links for each item
    for category in result.get("budget_breakdown", []):
        cat_name = category.get("category", "").lower()
        relevant_platforms = category_platforms.get(cat_name, default_platforms)

        for item in category.get("items", []):
            search_terms = item.get("search_terms") or item.get("name", "")
            if search_terms:
                item["shopping_links"] = {}
                q = urllib.parse.quote_plus(search_terms)
                if "amazon" in relevant_platforms:
                    item["shopping_links"]["amazon"] = f"https://www.amazon.in/s?k={q}"
                if "flipkart" in relevant_platforms:
                    item["shopping_links"]["flipkart"] = f"https://www.flipkart.com/search?q={q}"
                if "bigbasket" in relevant_platforms:
                    item["shopping_links"]["bigbasket"] = f"https://www.bigbasket.com/ps/?q={q}"
                if "swiggy" in relevant_platforms:
                    item["shopping_links"]["swiggy"] = f"https://www.swiggy.com/search?query={q}"
                if "zomato" in relevant_platforms:
                    item["shopping_links"]["zomato"] = f"https://www.zomato.com/search?q={q}"
                if "bookmyshow" in relevant_platforms:
                    item["shopping_links"]["bookmyshow"] = f"https://in.bookmyshow.com/search?q={q}"
                if "myntra" in relevant_platforms:
                    item["shopping_links"]["myntra"] = f"https://www.myntra.com/search?q={q}"
                if "meesho" in relevant_platforms:
                    item["shopping_links"]["meesho"] = f"https://www.meesho.com/search?q={q}"
                if "google" in relevant_platforms:
                    item["shopping_links"]["google"] = f"https://www.google.com/search?q={q}"
                if "booking" in relevant_platforms:
                    item["shopping_links"]["booking"] = f"https://www.booking.com/search.html?ss={q}"
                if "makemytrip" in relevant_platforms:
                    item["shopping_links"]["makemytrip"] = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}"
                if "oyorooms" in relevant_platforms:
                    item["shopping_links"]["oyorooms"] = f"https://www.oyorooms.com/search/?location={q}"
                if "nobroker" in relevant_platforms:
                    item["shopping_links"]["nobroker"] = f"https://www.nobroker.in/property/search?searchTerm={q}"

    # Add search links for venue suggestions
    venue_platforms = ["google", "booking", "makemytrip", "oyorooms", "nobroker"]
    for venue in result.get("venue_suggestions", []):
        search_terms = venue.get("search_terms") or venue.get("name", "")
        if search_terms:
            q = urllib.parse.quote_plus(search_terms)
            venue["search_links"] = {}
            if "google" in venue_platforms:
                venue["search_links"]["google"] = f"https://www.google.com/search?q={q}"
            if "booking" in venue_platforms:
                venue["search_links"]["booking"] = f"https://www.booking.com/search.html?ss={q}"
            if "makemytrip" in venue_platforms:
                venue["search_links"]["makemytrip"] = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}"
            if "oyorooms" in venue_platforms:
                venue["search_links"]["oyorooms"] = f"https://www.oyorooms.com/search/?location={q}"
            if "nobroker" in venue_platforms:
                venue["search_links"]["nobroker"] = f"https://www.nobroker.in/property/search?searchTerm={q}"

    return result

def _generate_fallback_party_recommendations(budget_input: PartyBudgetInput) -> dict:
    """Fallback party budget recommendations generator"""
    total = budget_input.total_budget
    guests = max(1, budget_input.num_guests)
    breakdown = []
    spent = 0.0

    # Venue
    venue_cost = 0.0 if (budget_input.venue_type and "home" in budget_input.venue_type.lower()) else total * 0.25
    spent += venue_cost
    breakdown.append({
        "category": "venue",
        "allocation": round(venue_cost, 2),
        "items": [{
            "name": f"{budget_input.venue_type or 'Home / Community Hall'} Reservation",
            "description": f"Dedicated space setup for {guests} guests with proper seating and ambience.",
            "estimated_price": round(venue_cost, 2),
            "quantity": 1,
            "search_terms": f"party banquet hall near me {budget_input.party_type}"
        }]
    })

    # Catering
    if budget_input.needs_catering:
        catering_cost = round(total * 0.45, 2)
        spent += catering_cost
        per_person = round(catering_cost / guests, 2)
        breakdown.append({
            "category": "catering",
            "allocation": catering_cost,
            "items": [{
                "name": "Customized Party Meal & Appetizer Box",
                "description": f"Multi-course buffet/snack menu tailored for {guests} guests (~₹{per_person}/person).",
                "estimated_price": catering_cost,
                "quantity": guests,
                "search_terms": f"bulk party catering food box {budget_input.party_type}"
            }]
        })

    # Decoration
    if budget_input.needs_decoration:
        decor_cost = round(total * 0.20, 2)
        spent += decor_cost
        breakdown.append({
            "category": "decoration",
            "allocation": decor_cost,
            "items": [{
                "name": "Theme Balloon Arch & Fairy Light Backdrop",
                "description": f"Complete DIY metallic balloon garland kit with warm fairy string lights and backdrop banner.",
                "estimated_price": decor_cost,
                "quantity": 1,
                "search_terms": f"{budget_input.party_type} theme decoration kit balloon arch"
            }]
        })

    # Entertainment
    if budget_input.needs_entertainment:
        ent_cost = round(total * 0.10, 2)
        spent += ent_cost
        breakdown.append({
            "category": "entertainment",
            "allocation": ent_cost,
            "items": [
                {
                    "name": "Bluetooth Party Speaker & Mic Rental / Purchase",
                    "description": "High-bass portable speaker with wireless microphone for karaoke and music.",
                    "estimated_price": round(ent_cost * 0.6, 2),
                    "quantity": 1,
                    "search_terms": "party bluetooth speaker with mic"
                },
                {
                    "name": "Party Games & Quiz Props",
                    "description": "Engaging group card games, board games, and trivia sets.",
                    "estimated_price": round(ent_cost * 0.4, 2),
                    "quantity": 1,
                    "search_terms": "party card games for adults and kids"
                }
            ]
        })

    # Contingency / Misc
    contingency = round(max(0.0, total * 0.05), 2)
    spent += contingency
    breakdown.append({
        "category": "contingency",
        "allocation": contingency,
        "items": [{
            "name": "Emergency Incidentals & Ice/Disposables",
            "description": "Buffer fund for extra ice cubes, paper disposables, and unexpected guest arrivals.",
            "estimated_price": contingency,
            "quantity": 1,
            "search_terms": "party disposable plates cups kit"
        }]
    })

    remaining = max(0.0, round(total - spent, 2))
    return {
        "total_budget": total,
        "budget_breakdown": breakdown,
        "venue_suggestions": [
            {
                "name": f"{budget_input.venue_type or 'Community Club Hall'}",
                "type": "Air-Conditioned Indoor Space",
                "capacity": guests,
                "estimated_cost": round(venue_cost, 2),
                "search_terms": f"{budget_input.party_type} venue rental nearby"
            }
        ],
        "remaining_budget": remaining,
        "additional_suggestions": [
            "Consider ordering platters directly through Swiggy Gourmet / Zomato Catering for timely deliveries.",
            "Set up a collaborative Spotify playlist so guests can queue their favorite party music.",
            "Prepare a photo corner with props to capture memorable moments within budget."
        ]
    }

def get_jewelry_recommendations(budget_input: JewelryBudgetInput, image_path: Optional[str] = None) -> dict:
    """Generate jewelry recommendations based on uploaded dress and budget in INR (India-specific)"""
    global vision_model, model

    base_prompt = f"""
I need jewelry recommendations for India with a total budget of ₹{budget_input.total_budget:.2f}.

Occasion: {budget_input.occasion}
Preferences: {budget_input.preferences or "Not specified"}
Provide only India-relevant styles, availability, and price ranges in INR.
"""

    if image_path and os.path.exists(image_path) and vision_model:
        try:
            img = Image.open(image_path)
            prompt = base_prompt + """
An image of the outfit is uploaded. Suggest jewelry that complements it, considering color, design, and occasion appropriateness.

Format the output as JSON:
{
  "outfit_analysis": {
    "colors": ["navy blue", "gold"],
    "style": "Traditional / Ethnic",
    "formality": "Festive / Wedding"
  },
  "total_budget": 0.0,
  "jewelry_recommendations": [
    {
      "item_type": "Necklace Set",
      "description": "Kundan and Pearl choker with matching earrings.",
      "style": "Ethnic Regal",
      "estimated_price": 0.0,
      "search_terms": "Kundan pearl choker necklace set"
    }
  ],
  "remaining_budget": 0.0,
  "styling_tips": [
    "Pair with simple bangles to keep focus on neckline."
  ]
}

Make sure prices are in INR and stay within budget.
Include Indian-friendly search terms for shopping.
"""
            response = vision_model.generate_content([prompt, img])
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini Vision jewelry error: {e}. Using fallback multimodal analysis.")
            result = _generate_fallback_jewelry_recommendations(budget_input, has_image=True)
    elif model:
        try:
            prompt = base_prompt + """
Format the output as JSON:
{
  "total_budget": 0.0,
  "jewelry_recommendations": [
    {
      "item_type": "Earrings / Studs",
      "description": "Elegant zircon studs or oxidized jhumkas.",
      "style": "Contemporary",
      "estimated_price": 0.0,
      "search_terms": "Silver oxidized jhumka earrings"
    }
  ],
  "remaining_budget": 0.0,
  "styling_tips": [
    "Keep jewelry minimal to match the outfit style."
  ]
}

Keep prices in INR and relevant to Indian brands.
"""
            response = model.generate_content(prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini API jewelry error: {e}. Using fallback generator.")
            result = _generate_fallback_jewelry_recommendations(budget_input, has_image=False)
    else:
        result = _generate_fallback_jewelry_recommendations(budget_input, has_image=bool(image_path))

    # Add shopping links for each item (India-specific)
    for item in result.get("jewelry_recommendations", []):
        search_terms = item.get("search_terms") or item.get("item_type", "")
        if search_terms:
            q = urllib.parse.quote_plus(search_terms)
            item["shopping_links"] = {
                "amazon": f"https://www.amazon.in/s?k={q}",
                "flipkart": f"https://www.flipkart.com/search?q={q}",
                "bluestone": f"https://www.bluestone.com/search.html?query={q}",
                "tanishq": f"https://www.tanishq.co.in/search?q={q}",
                "caratlane": f"https://www.caratlane.com/search?q={q}",
                "melorra": f"https://www.melorra.com/search?q={q}",
                "meesho": f"https://www.meesho.com/search?q={q}"
            }

    return result

def _generate_fallback_jewelry_recommendations(budget_input: JewelryBudgetInput, has_image: bool = False) -> dict:
    """Fallback jewelry recommendations generator"""
    total = budget_input.total_budget
    occ = budget_input.occasion.lower() if budget_input.occasion else "casual"
    
    recs = []
    spent = 0.0

    if "wedding" in occ or "traditional" in occ or "festive" in occ:
        recs = [
            {
                "item_type": "Necklace / Choker",
                "description": "Intricate Kundan and antique gold-plated choker set with micro pearls.",
                "style": "Royal Ethnic",
                "estimated_price": round(total * 0.45, 2),
                "search_terms": f"Tanishq gold plated kundan choker necklace"
            },
            {
                "item_type": "Earrings / Jhumkas",
                "description": "Matching chandelier chandbali or bell jhumkas with meenakari details.",
                "style": "Heritage Festive",
                "estimated_price": round(total * 0.25, 2),
                "search_terms": "CaratLane festive drop jhumkas"
            },
            {
                "item_type": "Bangles / Kada Set",
                "description": "Set of 4 brass gold-plated filigree bangles with ruby-red stones.",
                "style": "Traditional Filigree",
                "estimated_price": round(total * 0.20, 2),
                "search_terms": "BlueStone traditional filigree bangles"
            }
        ]
    elif "party" in occ or "cocktail" in occ or "reception" in occ:
        recs = [
            {
                "item_type": "Statement Pendant & Chain",
                "description": "Rose gold polished cubic zirconia crystal pendant necklace.",
                "style": "Contemporary Glam",
                "estimated_price": round(total * 0.40, 2),
                "search_terms": "Melorra rose gold geometric pendant chain"
            },
            {
                "item_type": "Cocktail Ring",
                "description": "Adjustable statement solitaire cocktail ring with baguette accents.",
                "style": "Modern Luxury",
                "estimated_price": round(total * 0.25, 2),
                "search_terms": "CaratLane solitaire cocktail ring"
            },
            {
                "item_type": "Tennis Bracelet",
                "description": "Sleek silver rhodium-finish tennis bracelet with sparkling stones.",
                "style": "Minimal Chic",
                "estimated_price": round(total * 0.25, 2),
                "search_terms": "Giva 925 sterling silver tennis bracelet"
            }
        ]
    else:
        # Casual / Daily wear
        recs = [
            {
                "item_type": "Bracelet",
                "description": "A simple, braided leather or minimal link bracelet with subtle metal accents.",
                "style": "Casual Chic",
                "estimated_price": round(total * 0.25, 2),
                "search_terms": "minimal silver link charm bracelet"
            },
            {
                "item_type": "Ring",
                "description": "A silver or dark grey metal band ring with sleek minimalist geometry.",
                "style": "Minimalist",
                "estimated_price": round(total * 0.25, 2),
                "search_terms": "minimalist sterling silver everyday band ring"
            },
            {
                "item_type": "Watch / Accent",
                "description": "A classic, everyday timepiece with clean dial and comfortable strap.",
                "style": "Classic Casual",
                "estimated_price": round(total * 0.40, 2),
                "search_terms": "Titan minimalist analog classic watch"
            }
        ]

    for item in recs:
        spent += item["estimated_price"]

    remaining = max(0.0, round(total - spent, 2))
    
    result = {
        "total_budget": total,
        "jewelry_recommendations": recs,
        "remaining_budget": remaining,
        "styling_tips": [
            "Keep the jewelry balanced: if wearing a prominent necklace, opt for simpler studs.",
            "Match the metal tone (yellow gold, rose gold, silver) with embroidery and watch accents.",
            "Select hallmarked 925 sterling silver or trusted brand gold finishes for long-lasting shine."
        ]
    }

    if has_image:
        result["outfit_analysis"] = {
            "colors": ["Classic Tones", "Navy/Teal", "Neutral Accents"],
            "style": "Modern / Smart Casual",
            "formality": "Semi-formal to Casual"
        }

    return result
