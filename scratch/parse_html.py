import re
from bs4 import BeautifulSoup

with open('html.txt', 'r', encoding='utf-8') as f:
    content = f.read()

# Let's find all buttons and inputs
soup = BeautifulSoup(content, 'html.parser')

print("--- BUTTONS ---")
for btn in soup.find_all('button'):
    print(f"Text: {btn.get_text(strip=True)}, Class: {btn.get('class')}, Attributes: {btn.attrs}")

print("\n--- INPUTS ---")
for inp in soup.find_all(['input', 'select', 'textarea']):
    print(f"Tag: {inp.name}, ID: {inp.get('id')}, Name: {inp.get('name')}, Type: {inp.get('type')}, Class: {inp.get('class')}")
