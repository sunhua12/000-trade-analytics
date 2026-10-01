SELECT period_start_date AS month,
      MAX(world_value) AS world_value,
      MAX(country_coverage) AS country_coverage,
      MAX(hhi) AS hhi, ANY_VALUE(hhi_status) AS hhi_status,
      MAX(IF(partner_code='458' AND partner_type='country',primary_value,NULL)) AS partner_value,
      MAX(IF(partner_code='458' AND partner_type='country',yoy,NULL)) AS partner_yoy
    FROM `trade-analytics-508604.trade_analytics_published.mart_us_semiconductor_supply_chain`
    WHERE period_start_date >= DATE '2024-01-01'
      AND period_start_date < DATE '2025-05-01'
      AND cmd_code='8542' AND hs_version='H6'
    GROUP BY month ORDER BY month
