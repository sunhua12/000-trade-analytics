-- Validation of detail grain, excluded aggregates and monetary validity.
select * from {{ ref('fct_multi_market_ic_imports') }}
where primary_value is null or primary_value < 0 or partner_code in ('0','490')
   or cmd_code not in ('854231','854232','854233','854239','854290')
   or flow_code != 'M' or hs_mapping_found is not true
