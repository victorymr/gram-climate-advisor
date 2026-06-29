#!/usr/bin/env python3
"""
IMD Data Extraction Workflow
Automated script to extract data from IMD screenshots and PDFs
"""

import pandas as pd
import json
import os
import subprocess
from datetime import datetime
from typing import Dict, List, Any

class IMDDataExtractor:
    """Extract and process IMD weather data from various sources"""
    
    def __init__(self, samples_dir="data/samples"):
        self.samples_dir = samples_dir
        self.extracted_data = {}
    
    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Extract text and structured data from IMD Agromet PDF"""
        try:
            # Use pdftotext to extract text
            text = subprocess.check_output(['pdftotext', pdf_path, '-'], 
                                         universal_newlines=True)
            
            # Parse the extracted text
            return self._parse_agromet_text(text)
            
        except Exception as e:
            print(f"Error extracting from PDF {pdf_path}: {str(e)}")
            return {}
    
    def _parse_agromet_text(self, text: str) -> Dict[str, Any]:
        """Parse structured data from Agromet advisory text"""
        data = {
            "district": "",
            "state": "",
            "date": "",
            "forecast": {},
            "crop_advisories": {},
            "warnings": []
        }
        
        lines = text.split('\n')
        
        # Extract basic info
        for i, line in enumerate(lines):
            if "District" in line and "Advisory" in line:
                # Extract district and state from title
                parts = line.split()
                for j, part in enumerate(parts):
                    if part == "District" and j > 0:
                        data["district"] = parts[j-1]
                    if "Andhra" in part:
                        data["state"] = "Andhra Pradesh"
            
            elif "Date :" in line:
                data["date"] = line.split("Date :")[1].strip()
            
            elif "Rainfall(mm)" in line:
                # Extract 5-day forecast table
                forecast_data = self._extract_forecast_table(lines[i+1:i+6])
                data["forecast"] = forecast_data
            
            elif "Crop Specific Advisory:" in line:
                # Extract crop advisories
                crop_data = self._extract_crop_advisories(lines[i+1:])
                data["crop_advisories"] = crop_data
            
            elif "Thunderstorm" in line:
                data["warnings"].append("thunderstorm")
            elif "lightening" in line:
                data["warnings"].append("lightning")
            elif "strong surface winds" in line:
                data["warnings"].append("strong_surface_winds")
        
        return data
    
    def _extract_forecast_table(self, table_lines: List[str]) -> Dict[str, Any]:
        """Extract 5-day forecast data from table"""
        forecast = {
            "rainfall": [],
            "max_temp": [],
            "min_temp": [],
            "warnings": []
        }
        
        for line in table_lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        rainfall = float(parts[0])
                        max_temp = float(parts[1])
                        min_temp = float(parts[2])
                        
                        forecast["rainfall"].append(rainfall)
                        forecast["max_temp"].append(max_temp)
                        forecast["min_temp"].append(min_temp)
                    except ValueError:
                        continue
        
        return forecast
    
    def _extract_crop_advisories(self, advisory_lines: List[str]) -> Dict[str, Any]:
        """Extract crop-specific advisories"""
        advisories = {}
        current_crop = ""
        current_advice = []
        
        for line in advisory_lines:
            if "CROP" in line and "(" in line and ")" in line:
                # Save previous crop data
                if current_crop and current_advice:
                    advisories[current_crop] = current_advice
                
                # Start new crop
                current_crop = line.strip()
                current_advice = []
            
            elif line.strip().startswith("•"):
                current_advice.append(line.strip())
        
        # Save last crop
        if current_crop and current_advice:
            advisories[current_crop] = current_advice
        
        return advisories
    
    def extract_from_rainfall_maps(self, image_files: List[str]) -> Dict[str, Any]:
        """Extract rainfall data from map images (manual input required)"""
        print("🗺️  Rainfall Map Analysis")
        print("Please provide the following information for each map:")
        
        rainfall_data = {}
        
        for image_file in image_files:
            print(f"\n📸 Analyzing: {image_file}")
            print("Enter rainfall values for pilot districts (or press Enter to skip):")
            
            districts = [
                "Bihar_Gaya", "Bihar_Patna",
                "Uttar_Pradesh_Varanasi", "Uttar_Pradesh_Lucknow", 
                "Maharashtra_Yavatmal", "Maharashtra_Nagpur",
                "Rajasthan_Jaipur", "Rajasthan_Jodhpur",
                "Andhra_Pradesh_Anantapur", "Andhra_Pradesh_Kurnool"
            ]
            
            map_data = {}
            for district in districts:
                value = input(f"  {district}: ")
                if value:
                    try:
                        map_data[district] = float(value)
                    except ValueError:
                        map_data[district] = value
            
            rainfall_data[image_file] = map_data
        
        return rainfall_data
    
    def update_forecast_csv(self, rainfall_data: Dict[str, Any], 
                           output_file: str = "data/admin_forecast_template.csv"):
        """Update the forecast CSV with extracted rainfall data"""
        try:
            # Read existing CSV
            df = pd.read_csv(output_file)
            
            # Update rainfall departure values
            for image_file, districts in rainfall_data.items():
                for district_key, value in districts.items():
                    state, district = district_key.split('_', 1)
                    
                    # Find matching row
                    mask = (df['state'] == state) & (df['district'] == district)
                    if mask.any():
                        if isinstance(value, (int, float)):
                            df.loc[mask, 'rainfall_since_june_1_pct_departure'] = value
                            print(f"✅ Updated {state}-{district}: {value}%")
            
            # Save updated CSV
            df.to_csv(output_file, index=False)
            print(f"📁 Updated forecast CSV: {output_file}")
            
        except Exception as e:
            print(f"❌ Error updating CSV: {str(e)}")
    
    def save_extracted_data(self, data: Dict[str, Any], 
                           output_file: str = "data/extracted_imd_data.json"):
        """Save extracted data to JSON file"""
        try:
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            print(f"💾 Saved extracted data to: {output_file}")
        except Exception as e:
            print(f"❌ Error saving data: {str(e)}")
    
    def run_extraction_workflow(self):
        """Run the complete data extraction workflow"""
        print("🌾 IMD Data Extraction Workflow")
        print("=" * 50)
        
        # Step 1: Extract from PDFs
        print("\n📄 Step 1: Extracting data from PDF files...")
        pdf_files = [f for f in os.listdir(self.samples_dir) if f.endswith('.pdf')]
        
        for pdf_file in pdf_files:
            pdf_path = os.path.join(self.samples_dir, pdf_file)
            print(f"📖 Processing: {pdf_file}")
            
            extracted = self.extract_from_pdf(pdf_path)
            if extracted:
                self.extracted_data[pdf_file] = extracted
                print(f"✅ Extracted data for {extracted.get('district', 'Unknown')}")
        
        # Step 2: Extract from images (manual input)
        print("\n🗺️  Step 2: Extracting data from rainfall maps...")
        image_files = [f for f in os.listdir(self.samples_dir) if f.endswith('.png')]
        
        if image_files:
            rainfall_data = self.extract_from_rainfall_maps(image_files)
            self.extracted_data['rainfall_maps'] = rainfall_data
            
            # Update CSV with rainfall data
            self.update_forecast_csv(rainfall_data)
        
        # Step 3: Save all extracted data
        print("\n💾 Step 3: Saving extracted data...")
        self.save_extracted_data(self.extracted_data)
        
        print("\n🎉 Extraction workflow completed!")
        
        return self.extracted_data

def main():
    """Main function to run the extraction workflow"""
    extractor = IMDDataExtractor()
    
    try:
        data = extractor.run_extraction_workflow()
        
        # Summary
        print(f"\n📊 Extraction Summary:")
        print(f"   - PDF files processed: {len([k for k in data.keys() if k.endswith('.pdf')])}")
        print(f"   - Image files processed: {len([k for k in data.keys() if 'rainfall' in k.lower()])}")
        print(f"   - Total data items: {len(data)}")
        
    except KeyboardInterrupt:
        print("\n⚠️  Extraction interrupted by user")
    except Exception as e:
        print(f"\n❌ Extraction failed: {str(e)}")

if __name__ == "__main__":
    main()
