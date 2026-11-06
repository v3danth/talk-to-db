-- TIER 3: "<live_table>_<digits>" snapshot copies of a live table, NOT referenced in application/ code.
-- 39 tables. Includes nep_* snapshots: the NEP app code is not on this machine, so review before running.
-- Run via drop_unwanted_tables.sh tier3 (which backs up first), not directly.
USE `mis_40_50`;
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_0703`;  -- snapshot of cbcs_absent_table_course_wise, ~2974 rows, 176 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_0704`;  -- snapshot of cbcs_absent_table_course_wise, ~5373 rows, 304 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_0902`;  -- snapshot of cbcs_absent_table_course_wise, ~6758 rows, 368 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_150`;  -- snapshot of cbcs_absent_table_course_wise, ~845894 rows, 43600 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_1504`;  -- snapshot of cbcs_absent_table_course_wise, ~2803 rows, 176 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_1604`;  -- snapshot of cbcs_absent_table_course_wise, ~845 rows, 80 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_1804`;  -- snapshot of cbcs_absent_table_course_wise, ~879 rows, 80 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_2102`;  -- snapshot of cbcs_absent_table_course_wise, ~1598 rows, 112 KB
DROP TABLE IF EXISTS `cbcs_absent_table_course_wise_2103`;  -- snapshot of cbcs_absent_table_course_wise, ~4910 rows, 288 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_0703`;  -- snapshot of cbcs_class_engaged_course_wise, ~340 rows, 64 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_0704`;  -- snapshot of cbcs_class_engaged_course_wise, ~452 rows, 64 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_0902`;  -- snapshot of cbcs_class_engaged_course_wise, ~717 rows, 96 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_150`;  -- snapshot of cbcs_class_engaged_course_wise, ~183217 rows, 15888 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_1504`;  -- snapshot of cbcs_class_engaged_course_wise, ~165 rows, 16 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_1604`;  -- snapshot of cbcs_class_engaged_course_wise, ~38 rows, 16 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_1804`;  -- snapshot of cbcs_class_engaged_course_wise, ~24 rows, 16 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_2102`;  -- snapshot of cbcs_class_engaged_course_wise, ~174 rows, 16 KB
DROP TABLE IF EXISTS `cbcs_class_engaged_course_wise_2103`;  -- snapshot of cbcs_class_engaged_course_wise, ~291 rows, 48 KB
DROP TABLE IF EXISTS `drop_2122_monsoon_109`;  -- snapshot of drop_2122_monsoon, ~107 rows, 16 KB
DROP TABLE IF EXISTS `drop_2122_monsoon_112`;  -- snapshot of drop_2122_monsoon, ~111 rows, 16 KB
DROP TABLE IF EXISTS `leave_auth_table_22`;  -- snapshot of leave_auth_table, ~26583 rows, 4128 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_0703`;  -- snapshot of nep_absent_table_course_wise, ~2726 rows, 192 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_0704`;  -- snapshot of nep_absent_table_course_wise, ~5039 rows, 336 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_0902`;  -- snapshot of nep_absent_table_course_wise, ~15278 rows, 1552 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_1504`;  -- snapshot of nep_absent_table_course_wise, ~3565 rows, 256 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_1531`;  -- snapshot of nep_absent_table_course_wise, ~101533 rows, 6672 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_1604`;  -- snapshot of nep_absent_table_course_wise, ~1154 rows, 96 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_1804`;  -- snapshot of nep_absent_table_course_wise, ~300 rows, 48 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_2102`;  -- snapshot of nep_absent_table_course_wise, ~1710 rows, 144 KB
DROP TABLE IF EXISTS `nep_absent_table_course_wise_2103`;  -- snapshot of nep_absent_table_course_wise, ~2929 rows, 208 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_0703`;  -- snapshot of nep_class_engaged_course_wise, ~373 rows, 64 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_0704`;  -- snapshot of nep_class_engaged_course_wise, ~462 rows, 64 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_0902`;  -- snapshot of nep_class_engaged_course_wise, ~670 rows, 96 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_1504`;  -- snapshot of nep_class_engaged_course_wise, ~212 rows, 48 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_1604`;  -- snapshot of nep_class_engaged_course_wise, ~64 rows, 16 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_1804`;  -- snapshot of nep_class_engaged_course_wise, ~26 rows, 16 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_197`;  -- snapshot of nep_class_engaged_course_wise, ~17662 rows, 1552 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_2102`;  -- snapshot of nep_class_engaged_course_wise, ~163 rows, 16 KB
DROP TABLE IF EXISTS `nep_class_engaged_course_wise_2103`;  -- snapshot of nep_class_engaged_course_wise, ~313 rows, 64 KB
SET FOREIGN_KEY_CHECKS = 1;
