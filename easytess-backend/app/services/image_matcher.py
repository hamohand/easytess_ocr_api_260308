"""
image_matcher.py - Scale-invariant image template matching using ORB features.
"""
import cv2
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def find_template_orb(image_path: str, template_path: str, min_matches: int = 10) -> dict:
    """
    Scale-invariant template matching using ORB features.
    
    This function finds a template image within a larger target image regardless
    of resolution differences. Uses ORB (Oriented FAST and Rotated BRIEF)
    keypoint detection and matching.
    
    Args:
        image_path: Path to the target image to search in.
        template_path: Path to the template image to find.
        min_matches: Minimum number of matches required to consider a valid detection.
    
    Returns:
        dict: {
            'found': bool,
            'x': float,  # Center X (0-1 relative)
            'y': float,  # Center Y (0-1 relative)
            'x_min': float,  # Bounding box min X
            'y_min': float,
            'x_max': float,
            'y_max': float,
            'confidence': float  # Average match distance (lower is better)
        }
    """
    try:
        # Load images in grayscale
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            logger.error(f"Could not load target image: {image_path}")
            return {'found': False, 'error': 'Could not load target image'}
        
        if template is None:
            logger.error(f"Could not load template image: {template_path}")
            return {'found': False, 'error': 'Could not load template image'}
            
        h, w = img.shape
        th, tw = template.shape

        # --- Method 1: ORB (Feature Invariant) ---
        orb_success = False
        orb_error = ""
        
        try:
            orb = cv2.ORB_create(nfeatures=1000)
            kp1, des1 = orb.detectAndCompute(template, None)
            kp2, des2 = orb.detectAndCompute(img, None)
            
            if des1 is not None and len(kp1) >= 4 and des2 is not None and len(kp2) >= 4:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = bf.match(des1, des2)
                matches = sorted(matches, key=lambda x: x.distance)
                
                if len(matches) >= min_matches:
                    good_matches = matches[:min(min_matches * 2, len(matches))]
                    
                    # Extract location of good matches
                    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                    
                    # Calculate homography and transform template corners to get exact bounding box
                    M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
                    
                    is_valid_transform = False
                    if M is not None:
                        # Transform template corners
                        pts_template_corners = np.float32([[0, 0], [0, th - 1], [tw - 1, th - 1], [tw - 1, 0]]).reshape(-1, 1, 2)
                        dst_corners = cv2.perspectiveTransform(pts_template_corners, M)
                        
                        # Validate the transformed polygon
                        area = cv2.contourArea(dst_corners)
                        orig_area = tw * th
                        is_convex = cv2.isContourConvex(np.int32(dst_corners))
                        
                        # The bounding box should remain a reasonable size and convex
                        if is_convex and (0.1 * orig_area < area < 10.0 * orig_area):
                            is_valid_transform = True
                            center = np.mean(dst_corners[:, 0, :], axis=0)
                            x_min = np.min(dst_corners[:, 0, 0])
                            y_min = np.min(dst_corners[:, 0, 1])
                            x_max = np.max(dst_corners[:, 0, 0])
                            y_max = np.max(dst_corners[:, 0, 1])
                            
                    if not is_valid_transform:
                        # Fallback to keypoints if homography fails or gives invalid results
                        pts = dst_pts.reshape(-1, 2)
                        center = pts.mean(axis=0)
                        x_min, y_min = pts.min(axis=0)
                        x_max, y_max = pts.max(axis=0)
                        
                    avg_distance = np.mean([m.distance for m in good_matches])
                    
                    result = {
                        'found': True,
                        'x': float(center[0] / w),
                        'y': float(center[1] / h),
                        'x_min': float(x_min / w),
                        'y_min': float(y_min / h),
                        'x_max': float(x_max / w),
                        'y_max': float(y_max / h),
                        'confidence': float(1.0 - (avg_distance / 256)),
                        'method': 'orb'
                    }
                    logger.info(f"✅ ORB Template found at ({result['x']:.3f}, {result['y']:.3f}) with {len(good_matches)} matches")
                    return result
                else:
                    orb_error = f"Insufficient matches: {len(matches)}"
            else:
                orb_error = f"Insufficient features (Template: {len(kp1) if kp1 else 0}, Target: {len(kp2) if kp2 else 0})"
        except Exception as e:
            orb_error = str(e)
            
        # --- Method 2: Pixel Matching (cv2.matchTemplate) ---
        # Fallback si ORB échoue (trop petit, pas assez de texture)
        logger.info(f"⚠️ ORB failed ({orb_error}) -> Trying Pixel Matching Fallback...")
        
        # Resize template if larger than image (impossible match)
        if th > h or tw > w:
             logger.warning("Template is larger than target image -> Pixel match impossible")
             return {'found': False, 'error': f"Template larger than image (ORB: {orb_error})"}

        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        # Seuil de confiance pour Pixel Match (ex: 0.7)
        threshold = 0.65 
        
        if max_val >= threshold:
            top_left = max_loc
            bottom_right = (top_left[0] + tw, top_left[1] + th)
            center_x = top_left[0] + tw / 2
            center_y = top_left[1] + th / 2
            
            result = {
                'found': True,
                'x': float(center_x / w),
                'y': float(center_y / h),
                'x_min': float(top_left[0] / w),
                'y_min': float(top_left[1] / h),
                'x_max': float(bottom_right[0] / w),
                'y_max': float(bottom_right[1] / h),
                'confidence': float(max_val),
                'method': 'pixel'
            }
            logger.info(f"✅ Pixel Template found at ({result['x']:.3f}, {result['y']:.3f}) with conf={max_val:.2f}")
            return result
        else:
            logger.warning(f"❌ Pixel Match failed (Best conf: {max_val:.2f} < {threshold})")
            return {'found': False, 'error': f"All methods failed. ORB: {orb_error}. Pixel: low confidence ({max_val:.2f})"}

    except Exception as e:
        logger.error(f"Error in template matching: {e}")
        return {'found': False, 'error': str(e)}


def extract_and_save_template(image_path: str, coords: list, output_path: str) -> bool:
    """
    Extract a region from an image and save as a template.
    
    Args:
        image_path: Path to the source image.
        coords: [x1, y1, x2, y2] in relative coordinates (0-1).
        output_path: Path to save the extracted template.
    
    Returns:
        bool: True if successful.
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Could not load image: {image_path}")
            return False
        
        h, w = img.shape[:2]
        x1, y1, x2, y2 = coords
        
        # Convert relative to absolute coordinates
        abs_x1 = int(x1 * w)
        abs_y1 = int(y1 * h)
        abs_x2 = int(x2 * w)
        abs_y2 = int(y2 * h)
        
        # Extract region
        template = img[abs_y1:abs_y2, abs_x1:abs_x2]
        
        if template.size == 0:
            logger.error(f"Empty template region: {coords}")
            return False
        
        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Save template
        cv2.imwrite(str(output_path), template)
        logger.info(f"✅ Template saved: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error extracting template: {e}")
        return False
