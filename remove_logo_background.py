from PIL import Image
import sys

if len(sys.argv) != 4:
    print("Usage: python remove_logo_background.py input.png output.png tolerance")
    sys.exit(1)

input_path = sys.argv[1]
output_path = sys.argv[2]
try:
    tolerance = int(sys.argv[3])
except ValueError:
    print("Tolerance must be an integer, e.g. 20")
    sys.exit(1)

img = Image.open(input_path).convert("RGBA")
pixels = img.load()

for y in range(img.height):
    for x in range(img.width):
        r, g, b, a = pixels[x, y]
        # Remove near-white / light background. Adjust tolerance as needed.
        if a > 0 and r >= 255 - tolerance and g >= 255 - tolerance and b >= 255 - tolerance:
            pixels[x, y] = (255, 255, 255, 0)

img.save(output_path)
print(f"Saved cleaned logo to {output_path}")
