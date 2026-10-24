"""Starter menu. Edit this list, delete data/orders.db, restart to reload it.

After the first run the menu lives in the database; change availability from the
kitchen screen. Prices are whole rupees.
"""

CATEGORIES = ["Starters", "Biryani", "Curries", "Sides & Drinks"]

# Packaged items sold at their printed MRP: GST is already inside the MRP, so none is added on the bill.
PACKAGED = {"d5"}

# id, category, name, description, price, veg, spice (0-3), hue (0-360, tile colour), available
ITEMS = [
    ("s1", "Starters", "Chicken Lollipop", "Five pieces, fried crisp in our house masala. Moderately spicy.", 370, 0, 2, 18, 1),
    ("s2", "Starters", "Lemon Chicken", "Boneless chicken with fresh lemon and house spice mix.", 375, 0, 2, 48, 1),
    ("s3", "Starters", "Chilly Chicken", "Boneless pieces with green chillies and curry leaves, pan fried.", 375, 0, 3, 8, 1),
    ("s4", "Starters", "Chicken Kabab", "Six bone-in pieces, deep fried in masala. Not very spicy.", 360, 0, 1, 14, 1),
    ("s5", "Starters", "Pepper Chicken", "Chicken pieces with crushed pepper and curry leaves.", 360, 0, 3, 28, 1),
    ("s6", "Starters", "Chicken 65", "Boneless chicken, pan fried with spice mix and green chillies.", 375, 0, 2, 12, 1),
    ("s7", "Starters", "Nati Chicken Fry", "Country chicken, seven to eight pieces, deep fried. Pretty spicy.", 425, 0, 3, 22, 1),
    ("s8", "Starters", "Mutton Fry", "Six to seven pieces cooked semi-gravy in a kadhai.", 400, 0, 2, 10, 1),
    ("s9", "Starters", "Paneer Fry", "Paneer cubes tossed with onions, chillies and curry leaves.", 320, 1, 2, 38, 1),
    ("s10", "Starters", "Gobi 65", "Crisp cauliflower in a red masala coating.", 260, 1, 2, 6, 1),
    ("b1", "Biryani", "Chicken Dum Biryani", "Basmati sealed and slow cooked with bone-in chicken.", 340, 0, 2, 36, 1),
    ("b2", "Biryani", "Mutton Biryani", "Tender mutton layered with saffron rice.", 460, 0, 2, 30, 1),
    ("b3", "Biryani", "Egg Biryani", "Boiled eggs in spiced rice with fried onions.", 280, 0, 1, 44, 1),
    ("b4", "Biryani", "Veg Biryani", "Seasonal vegetables and rice with whole spices.", 270, 1, 1, 92, 1),
    ("b5", "Biryani", "Paneer Biryani", "Paneer marinated in curd and spices, dum cooked.", 310, 1, 1, 52, 1),
    ("c1", "Curries", "Andhra Chicken Curry", "Bone-in chicken in a hot, tangy Andhra gravy.", 350, 0, 3, 16, 1),
    ("c2", "Curries", "Butter Chicken", "Tandoori chicken in a mild tomato and butter gravy.", 380, 0, 0, 20, 1),
    ("c3", "Curries", "Paneer Butter Masala", "Paneer in a creamy tomato gravy.", 320, 1, 0, 26, 1),
    ("c4", "Curries", "Dal Tadka", "Yellow lentils tempered with garlic and cumin.", 220, 1, 1, 46, 1),
    ("d1", "Sides & Drinks", "Steamed Rice", "A bowl of plain basmati rice.", 120, 1, 0, 60, 1),
    ("d2", "Sides & Drinks", "Butter Naan", "Soft naan brushed with butter.", 50, 1, 0, 40, 1),
    ("d3", "Sides & Drinks", "Onion Raita", "Curd with onion and cucumber.", 60, 1, 0, 150, 1),
    ("d4", "Sides & Drinks", "Gulab Jamun", "Two warm milk dumplings in sugar syrup.", 90, 1, 0, 24, 1),
    ("d5", "Sides & Drinks", "Soft Drink", "300 ml bottle, chilled.", 50, 1, 0, 200, 1),
]
