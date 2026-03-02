import cv2
import numpy as np
import logging
logging.basicConfig(level=logging.INFO)

from app.services.image_matcher import extract_and_save_template, find_template_orb

img = np.zeros((600, 800, 3), dtype=np.uint8)
cv2.rectangle(img, (200, 200), (300, 300), (255, 255, 255), -1)
# Some text
cv2.putText(img, "DROITE", (210, 250), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
cv2.imwrite('fake_img.jpg', img)

# 0.25 to 0.375
extract_and_save_template('fake_img.jpg', [0.25, 0.333, 0.375, 0.50], 'fake_template.png')

res = find_template_orb('fake_img.jpg', 'fake_template.png')
print("Find template result:", res)
