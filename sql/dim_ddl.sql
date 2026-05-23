-- robot_id → production_line + station_type 매핑 dim VIEW
-- 학습/시연용 임의 매핑 (실제 공정 무관). 공정관리자 portal 의 line 그룹뷰 패널에서 JOIN.
--
-- 매핑:
--   ROBOT-00001 ~ 00250  → LINE-A 용접
--   ROBOT-00251 ~ 00500  → LINE-B 도장
--   ROBOT-00501 ~ 00750  → LINE-C 조립
--   ROBOT-00751 ~ 01000  → LINE-D 검사
--   그 외 (1001+ 또는 비표준 포맷) → LINE-X unknown
--
-- VIEW 사용 이유:
--   - 매핑 변경 시 ALTER 한 번으로 끝 (S3 dim 파일 재업로드 불필요)
--   - 1000 robot 규모에선 Athena 쿼리 성능 영향 미미
--   - 라인이 더 많아지거나 동적 부여 필요해지면 S3 CSV 백업 dim 으로 전환

CREATE OR REPLACE VIEW robot_telemetry_db.dim_robot_line AS
SELECT
    robot_id,
    CASE
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 1   AND 250 THEN 'LINE-A'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 251 AND 500 THEN 'LINE-B'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 501 AND 750 THEN 'LINE-C'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 751 AND 1000 THEN 'LINE-D'
        ELSE 'LINE-X'
    END AS production_line,
    CASE
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 1   AND 250 THEN '용접'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 251 AND 500 THEN '도장'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 501 AND 750 THEN '조립'
        WHEN TRY_CAST(SUBSTR(robot_id, 7) AS INTEGER) BETWEEN 751 AND 1000 THEN '검사'
        ELSE 'unknown'
    END AS station_type
FROM (
    SELECT DISTINCT robot_id FROM robot_telemetry_db.gold_robot_daily_stats
);
