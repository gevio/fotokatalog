import exifread
from PIL import Image
from PIL.ExifTags import TAGS, IFD, GPSTAGS

path = r'E:\DCIM\03_Privat\Best of Valais\Originale\20230327_174322.jpg'

print("=== EXIFREAD ===")
with open(path, 'rb') as f:
    tags = exifread.process_file(f)
print(f"{len(tags)} Tags gefunden")
for k, v in sorted(tags.items())[:15]:
    print(f"  {k} = {v}")

print("\n=== PILLOW ===")
img = Image.open(path)
exif = img.getexif()
print(f"{len(exif)} Tags gefunden")
for k, v in list(exif.items())[:10]:
    print(f"  {TAGS.get(k, k)} = {v}")

try:
    gps = exif.get_ifd(IFD.GPSInfo)
    print(f"\nGPS: {len(gps)} Eintraege")
    for k, v in gps.items():
        print(f"  {GPSTAGS.get(k, k)} = {v}")
except:
    print("\nKein GPS IFD")
