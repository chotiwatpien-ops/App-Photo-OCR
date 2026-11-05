-- How many rows would have waited in the review queue under the audit batch 2 rules (commit 93843a1)?
-- Read-only. Run in Neon → SQL Editor, then send back the result table.
--
--   approved_auto      rows the round approved by itself (the scale)
--   turbo_filled       auto-approved rows whose turbo the system filled from net−base
--   turbo_witnessed    ...of those, rows where passenger fare − Grab's cut confirms the net (±1)
--   tip_unsure         auto-approved rows with a derived base, a tip, and a bonus at least the tip
--
-- Extra rows in the queue per week ≈ (turbo_filled − turbo_witnessed) + tip_unsure.
-- It is an upper bound: the left-screen net, the other witness, is not stored on the row.
SELECT j.date_from                                                        AS week_from,
       COUNT(*) FILTER (WHERE t.auto_approved = 1)                         AS approved_auto,
       COUNT(*) FILTER (WHERE t.auto_approved = 1
                          AND t.note LIKE '%เติม Turbo%')                   AS turbo_filled,
       COUNT(*) FILTER (WHERE t.auto_approved = 1
                          AND t.note LIKE '%เติม Turbo%'
                          AND t.passenger_total IS NOT NULL
                          AND t.grab_commission IS NOT NULL
                          AND ABS((t.passenger_total - t.grab_commission) - t.net_earnings) <= 1)
                                                                           AS turbo_witnessed,
       COUNT(*) FILTER (WHERE t.auto_approved = 1
                          AND t.note LIKE '%คำนวณจาก net%'
                          AND COALESCE(t.tip, 0) > 0
                          AND COALESCE(t.bonus, 0) - t.tip >= t.tip)       AS tip_unsure
FROM trips t
JOIN jobs j ON j.id = t.job_id
WHERE t.committed = 1
  AND j.date_from >= '2026-08-31'
GROUP BY j.date_from
ORDER BY j.date_from;
