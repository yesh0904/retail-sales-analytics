-- Q1 Revenue by year: yearly sales, profit and growth
WITH y AS (
    SELECT year, ROUND(SUM(sales),2) AS sales, ROUND(SUM(profit),2) AS profit
    FROM sales GROUP BY year
)
SELECT year, sales, profit,
       ROUND(100.0 * profit / sales, 1) AS margin_pct,
       ROUND(100.0 * (sales - LAG(sales) OVER (ORDER BY year)) / LAG(sales) OVER (ORDER BY year), 1) AS yoy_growth_pct
FROM y ORDER BY year;

-- Q2 Top 10 sub-categories by profit
SELECT category, sub_category,
       ROUND(SUM(sales),0) AS sales, ROUND(SUM(profit),0) AS profit,
       ROUND(100.0 * SUM(profit) / SUM(sales), 1) AS margin_pct
FROM sales GROUP BY category, sub_category
ORDER BY profit DESC LIMIT 10;

-- Q3 Loss-making sub-categories by discount level
SELECT sub_category,
       CASE WHEN discount > 0.3 THEN 'Deep (>30%)' WHEN discount > 0 THEN 'Light (1-30%)' ELSE 'None' END AS discount_level,
       COUNT(*) AS order_lines, ROUND(SUM(profit),0) AS profit
FROM sales GROUP BY sub_category, discount_level
HAVING SUM(profit) < 0
ORDER BY profit;

-- Q4 Top 10 customers: lifetime value with rank
SELECT customer_id, customer_name, segment, region,
       COUNT(DISTINCT order_id) AS orders, ROUND(SUM(sales),0) AS lifetime_sales,
       RANK() OVER (ORDER BY SUM(sales) DESC) AS sales_rank
FROM sales GROUP BY customer_id, customer_name, segment, region
ORDER BY lifetime_sales DESC LIMIT 10;

-- Q5 Regional running total: monthly cumulative sales per region (2025)
SELECT region, year_month,
       ROUND(SUM(sales),0) AS monthly_sales,
       ROUND(SUM(SUM(sales)) OVER (PARTITION BY region ORDER BY year_month),0) AS cumulative_sales
FROM sales WHERE year = 2025
GROUP BY region, year_month ORDER BY region, year_month;

-- Q6 Shipping performance: speed and profitability by ship mode
SELECT ship_mode, COUNT(DISTINCT order_id) AS orders,
       ROUND(AVG(ship_days),2) AS avg_ship_days,
       ROUND(100.0 * SUM(profit) / SUM(sales), 1) AS margin_pct
FROM sales GROUP BY ship_mode ORDER BY avg_ship_days;

-- Q7 Repeat vs one-time customers
WITH c AS (
    SELECT customer_id, COUNT(DISTINCT order_id) AS n_orders, SUM(sales) AS sales
    FROM sales GROUP BY customer_id
)
SELECT CASE WHEN n_orders = 1 THEN 'One-time' WHEN n_orders <= 5 THEN '2-5 orders' ELSE '6+ orders' END AS customer_type,
       COUNT(*) AS customers, ROUND(SUM(sales),0) AS revenue,
       ROUND(100.0 * SUM(sales) / (SELECT SUM(sales) FROM sales), 1) AS revenue_share_pct
FROM c GROUP BY customer_type ORDER BY revenue DESC
