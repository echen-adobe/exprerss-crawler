import os
from PIL import Image, ImageChops
import imagehash
import json
from pathlib import Path
from difflib import SequenceMatcher
import numpy as np
import argparse

def calculate_image_hash_similarity(img1, img2):
    hash_1 = imagehash.average_hash(img1)
    hash_2 = imagehash.average_hash(img2)
    return { 
        "hamming_distance" : hash_1 - hash_2
    }

def generate_image_diffs(hamming_threshold=2):
    control_dir = "./qa/control"
    experimental_dir = "./qa/experimental"
    output_dir = "./qa/diff"
    diff_results = {}
    metrics = {}
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    for filename in os.listdir(control_dir):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            control_path = os.path.join(control_dir, filename)
            experimental_path = os.path.join(experimental_dir, filename)
            if os.path.exists(experimental_path):
                # Open both images
                control_img = Image.open(control_path)
                experimental_img = Image.open(experimental_path)
                diff_path = '' 

                # Get dimensions of both images
                control_width, control_height = control_img.size
                experimental_width, experimental_height = experimental_img.size
                control_cropped = False
                experimental_cropped = False
                # Determine which image is larger and crop it to match the smaller one
                if control_width * control_height > experimental_width * experimental_height:
                    # Control image is larger, crop it to match experimental
                    control_img = control_img.crop((0, 0, experimental_width, experimental_height))
                    control_cropped = True
                elif experimental_width * experimental_height > control_width * control_height:
                    # Experimental image is larger, crop it to match control
                    experimental_img = experimental_img.crop((0, 0, control_width, control_height))
                    experimental_cropped = True
                
                control_img = control_img.convert('L')
                experimental_img = experimental_img.convert('L')

                
                
                # # Calculate similarities
                image_similarities = calculate_image_hash_similarity(control_img, experimental_img)
                
                h_d =  image_similarities["hamming_distance"]
                significant_diff = h_d > hamming_threshold

                if (significant_diff):
                    diff_img = ImageChops.difference(control_img, experimental_img)
                    diff_path = os.path.join(output_dir, f"diff_{filename}")
                    diff_img.save(diff_path)
                
                if (h_d not in metrics):
                    metrics[h_d] = 0
                metrics[h_d] += 1
                    
                # Store results
                diff_results[filename] = {
                    "diff" : h_d,
                    "diff_path": diff_path,
                    "has_significant_differences": significant_diff,
                    "hamming_threshold_used": hamming_threshold,
                    "control_cropped": control_cropped,
                    "experimental_cropped": experimental_cropped
                }
    
   
    diff_results['metrics'] = metrics
    # Save results to JSON file
    with open('diff_urls.json', 'w', encoding='utf-8') as f:
        json.dump(diff_results, f, indent=4)
    
    print(f"\nDiff generation complete using hamming threshold: {hamming_threshold}")
    print(f"Results saved to diff_urls.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Calculate image diffs with configurable hamming distance threshold')
    parser.add_argument('--threshold', type=int, default=2,
                      help='Hamming distance threshold for determining significant differences (default: 2)')
    
    args = parser.parse_args()
    
    print(f"Using hamming distance threshold: {args.threshold}")
    generate_image_diffs(args.threshold)
