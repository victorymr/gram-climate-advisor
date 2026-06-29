# IMD Weekly Rainfall Regions Table Interpretation Methodology

## Table Structure Analysis

### Format:
- **Rows**: Meteorological subdivisions (36 subdivisions across India)
- **Columns**: Dates (cumulative rainfall since June 1st)
- **Cells**: Color-coded rainfall departure percentages

### Color Legend (Typical IMD Scale):
- **Dark Blue**: Large Excess (≥60% above normal)
- **Light Blue**: Excess (20% to 59% above normal)  
- **Green**: Normal (-19% to +19% of normal)
- **Yellow/Orange**: Deficient (-20% to -59% below normal)
- **Red**: Large Deficient (≤-60% below normal)

## Precise Extraction Process

### Step 1: Identify Target Subdivisions
For each pilot district, locate its meteorological subdivision:
- Bihar & Jharkhand (BJ) → Gaya, Patna
- East Uttar Pradesh (EUP) → Varanasi, Lucknow
- Vidarbha (VID) → Yavatmal, Nagpur  
- West Rajasthan (WR) → Jaipur, Jodhpur
- South Interior Karnataka (SIK) → Anantapur, Kurnool

### Step 2: Locate Current Date Column
Find the column for the current date (2026-06-27) in the table
- This represents cumulative rainfall since June 1st
- Each column shows progressive accumulation

### Step 3: Extract Color Information
For each subdivision's row, identify the color in the current date column:
- Document exact color observed
- Note any color gradients or patterns
- Record if cell is blank or has special indicators

### Step 4: Convert Color to Percentage Range
Map colors to standard IMD percentage ranges:
- Dark Blue → +60% to +100%
- Light Blue → +20% to +59%
- Green → -19% to +19%
- Yellow/Orange → -20% to -59%
- Red → -60% to -100%

### Step 5: Estimate Specific Value
Within each range, use midpoint estimation:
- Large Excess: +80% (midpoint of +60% to +100%)
- Excess: +40% (midpoint of +20% to +59%)
- Normal: 0% (midpoint of -19% to +19%)
- Deficient: -40% (midpoint of -20% to -59%)
- Large Deficient: -80% (midpoint of -60% to -100%)

## Data Quality Framework

### HIGH CONFIDENCE:
- Clear color identification
- Standard IMD color scheme
- No ambiguity in cell location

### MEDIUM CONFIDENCE:
- Color borderline between categories
- Faded or unclear printing
- Multiple similar color shades

### LOW CONFIDENCE:
- Unclear subdivision identification
- Color outside standard range
- Missing or damaged cells

## Extraction Template

For each district:
```
District: [Name]
Subdivision: [Code]
Date: [YYYY-MM-DD]
Observed Color: [Color description]
Color Category: [Large Excess/Excess/Normal/Deficient/Large Deficient]
Estimated Percentage: [Value]
Confidence Level: [High/Medium/Low]
Notes: [Any observations or uncertainties]
```

## Quality Control Checks

1. **Cross-reference subdivision boundaries** with official IMD maps
2. **Verify color interpretation** against IMD legend
3. **Check for seasonal patterns** (monsoon progression)
4. **Validate against known weather events** (heat waves, floods)
5. **Document any anomalies** or unusual patterns

## Limitations and Assumptions

1. **Color perception** may vary based on image quality
2. **Midpoint estimation** is a simplification of actual distribution
3. **Subdivision boundaries** may not perfectly match district boundaries
4. **Image resolution** may affect color accuracy
5. **Printing variations** may alter color appearance

## Required Tools

1. **High-resolution image** of IMD Weekly Rainfall Regions table
2. **IMD color legend** for reference
3. **Subdivision boundary map** for verification
4. **Current date reference** for column identification
