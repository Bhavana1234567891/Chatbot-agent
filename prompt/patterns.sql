-- Example questions and the SQL to copy.
-- Replace brand, product_name, channel_id, and color words with values
-- looked up from the table. Do not invent spellings.
-- One row is one colorway. A style is brand + product_name.
-- Compare selling strength with rank_percentile (higher is better).
-- Never sort or compare retailers by rank_absolute.

-- 1. Best and worst color of one style.
-- Read the first row as the best color and the last row as the worst,
-- but only when rank_percentile is not the same on every row.
-- If every row shares one percentile, the rank is style-level:
-- say so, and do not name a winning color.
SELECT
    color,
    rank_percentile,
    rank_label
FROM products
WHERE brand = 'AE'
  AND product_name = 'AE Corduroy Tie-Front Lace Mini Dress'
  AND color IS NOT NULL
  AND TRIM(color) <> ''
ORDER BY rank_percentile DESC;

-- 2. Best sellers across retailers.
-- rank_percentile is the only rank column that is safe here.
-- Do not ORDER BY rank_absolute. A small rank_absolute at one
-- channel_id is not better than a larger one at another channel_id.
SELECT
    channel_id,
    brand,
    product_name,
    color,
    rank_percentile,
    rank_label
FROM products
WHERE rank_label = 'Best Seller'
ORDER BY rank_percentile DESC
LIMIT 20;

-- 3. Do black and navy beat pastels inside the same silhouette?
-- Silhouette is words in product_name (mini, midi, maxi, halter).
-- There is no silhouette column. "Silhouette" inside an Aritzia
-- product name is a fabric line, not the dress shape.
-- First list the raw colors, then bucket them. Do not match the
-- word pastel as a stored color. It is not a value in this table.
SELECT DISTINCT color
FROM products
WHERE LOWER(product_name) LIKE '%halter%'
  AND color IS NOT NULL
  AND TRIM(color) <> ''
ORDER BY color;

-- After the color list is known, bucket only colors that appeared.
-- Extend the WHEN list from that list. Leave unmatched colors in other.
SELECT
    CASE
        WHEN LOWER(color) LIKE '%black%' THEN 'black'
        WHEN LOWER(color) LIKE '%navy%' THEN 'navy'
        WHEN LOWER(color) LIKE '%pink%'
          OR LOWER(color) LIKE '%cream%'
          OR LOWER(color) LIKE '%lilac%'
          OR LOWER(color) LIKE '%lavender%'
          OR LOWER(color) LIKE '%blush%'
          THEN 'pastel'
        ELSE 'other'
    END AS color_family,
    MEDIAN(rank_percentile) AS median_percentile,
    COUNT(*) AS colorways
FROM products
WHERE LOWER(product_name) LIKE '%halter%'
  AND color IS NOT NULL
  AND TRIM(color) <> ''
GROUP BY 1
ORDER BY median_percentile DESC;

-- 4. Colors missing on a strong style that competitors already sell.
-- A strong style has a high rank_percentile on brand + product_name.
-- Query A is the colors that style already sells.
-- Query B is colors on other brands with the same silhouette words
-- and a strong rank. Compare families in the answer.
-- Do not EXCEPT raw color strings across brands: "Muted Navy" and
-- "Navy" are the same family and will not match as text.
-- Query A
SELECT DISTINCT color
FROM products
WHERE brand = 'AE'
  AND product_name = 'AE Corduroy Tie-Front Lace Mini Dress'
  AND color IS NOT NULL
  AND TRIM(color) <> '';

-- Query B
SELECT
    brand,
    color,
    MEDIAN(rank_percentile) AS median_percentile
FROM products
WHERE brand <> 'AE'
  AND LOWER(product_name) LIKE '%mini%'
  AND rank_percentile >= 90
  AND color IS NOT NULL
  AND TRIM(color) <> ''
GROUP BY brand, color
ORDER BY median_percentile DESC;

-- 5. One retailer.
-- This table has no retailer-name column. Filter channel_id.
-- American Eagle is channel_id 30. The brand value on those rows is AE.
SELECT
    brand,
    product_name,
    color,
    rank_percentile,
    rank_label,
    selling_price_USD
FROM products
WHERE channel_id = 30
  AND rank_label = 'Best Seller'
ORDER BY rank_percentile DESC
LIMIT 20;

-- 6. Picture, product page, or the whole row.
-- feature_image and pdp_url are already on the row. Do not use get_values for them.
-- Copy the URL from the result. Do not invent one.
-- Picture, photo, or image: feature_image only.
SELECT
    product_name,
    color,
    feature_image
FROM products
WHERE brand = 'AE'
  AND product_name = 'AE Corduroy Tie-Front Lace Mini Dress';

-- Product link, product page, or pdp url: pdp_url only.
SELECT
    product_name,
    color,
    pdp_url
FROM products
WHERE brand = 'AE'
  AND product_name = 'AE Corduroy Tie-Front Lace Mini Dress';

-- Whole row, every column, or all values: include both URLs with the other fields.
SELECT
    product_name,
    color,
    rank_percentile,
    rank_label,
    selling_price_USD,
    feature_image,
    pdp_url
FROM products
WHERE brand = 'AE'
  AND product_name = 'AE Corduroy Tie-Front Lace Mini Dress';

-- 7. Top rated dresses, including a rupee price band.
-- "Top rated" is the rating column, not rank_percentile.
-- Blank ratings are missing. Do not treat them as zero.
-- "rs", "rupees", and "INR" filter selling_price_INR. This is in scope.
SELECT
    brand,
    product_name,
    color,
    rating,
    selling_price_INR
FROM products
WHERE rating IS NOT NULL
  AND selling_price_INR BETWEEN 10000 AND 20000
ORDER BY rating DESC
LIMIT 20;

-- 8. Top ranked dresses in a rupee price band.
-- "Top ranked" is rank_percentile. Higher is better.
-- Do not refuse a price filter. Drop the WHERE line when no price is asked.
SELECT
    brand,
    product_name,
    color,
    rank_percentile,
    rank_label,
    selling_price_INR
FROM products
WHERE selling_price_INR BETWEEN 10000 AND 20000
ORDER BY rank_percentile DESC
LIMIT 20;
