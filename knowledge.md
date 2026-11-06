# Domain notes

Business rules the agent should know. Edit freely; the server reads this at startup (restart after changes).
Add a line whenever the agent gets something wrong, e.g. "active students = users.status='A'" once you confirm it.

## Identity
- `users.id` is the login id of everyone: admission number (`admn_no`) for students, employee number (`emp_no`) for staff.
- `user_details.id` = `users.id`. Names: `first_name`, `middle_name`, `last_name`. Department: `user_details.dept_id` -> `departments.id` (`departments.name`, `departments.type`).
- Role: `users.auth_id` / `user_auth_types(id, auth_id)` -> `auth_types(id, type)`. A user can have several auth types.
- Students: `stu_academic.admn_no` = `user_details.id` (course, branch, current semester, enrollment_year); `stu_details.admn_no` for personal extras.
- Employees: `emp_basic_details.emp_no` = `user_details.id`; designation -> `designations.id`.

## Academics
- Two curricula coexist: CBCS (`cbcs_*`, older batches) and NEP (`nep_*`, current batches). Questions about "current" courses, attendance or marks usually mean NEP; check both if unsure.
- Semester registration: `reg_regular_form` (CBCS era) and `nep_reg_form` (NEP), keyed by `admn_no`, `session_year`, `session`, `semester`; approval in `hod_status` / `acad_status`.
- Results: `final_semwise_marks_foil_freezed` (one row per student per semester result: gpa, cgpa, status) with subject-level rows in `final_semwise_marks_foil_desc_freezed` (`foil_id` -> `id`). "Freezed" = published/final.
- Course and branch names: `cbcs_courses`, `cbcs_branches` (also `cs_courses`, `cs_branches` in older code).

## Conventions
- `session_year` looks like '2024-2025'; `session` is the term (e.g. Monsoon / Winter / Summer). Check the real values with SELECT DISTINCT before filtering.
- Tables ending in `_log` are audit trails; `_desc` holds line items for a parent table; dated or `_bkp` names are snapshots - don't use them for current answers.
