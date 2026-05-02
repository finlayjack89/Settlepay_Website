import xml.etree.ElementTree as ET
import re

svg_file = '/Users/finlaysalisbury/Documents/SettlePay/Settlepay_Website/untitled folder/Klarna.svg'

def extract_coords(d_string):
    # Find all numbers (including negative and decimals)
    numbers = [float(x) for x in re.findall(r'-?\d+\.?\d*', d_string)]
    # This is a rough estimation for path bounding box (just min/max of all numbers).
    # Since SVG commands can be complex, a true bounding box requires path parsing,
    # but for simple scaling, finding min/max of all coordinates gives a good approximation.
    pass

# We will just use a simpler approach: regex search for all x and y coordinates if possible,
# or we can write a more accurate parser. Wait, we have the file contents.
with open(svg_file, 'r') as f:
    content = f.read()

# Let's extract all numbers from the file:
# Actually, the SVG has a <rect x="801.36" y="448.89" width="24.03" height="102.98"/>
# And other paths.
# Let's just crop it tightly based on min/max of all numeric values that represent coords.
# A simpler way is to just use a generous crop because the current one is 2880x1000!
# We found: x between 800 and 2200. Y between 430 and 570.
# We will set viewBox="780 430 1440 140"
content = re.sub(r'viewBox="[^"]+"', 'viewBox="780 430 1440 140"', content)

with open(svg_file, 'w') as f:
    f.write(content)
print("Updated Klarna SVG viewBox to '780 430 1440 140'")

