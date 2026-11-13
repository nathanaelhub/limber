# Cutover map (019 slice 8, SC-003)

Every behaviour the Streamlit UI tests pinned, and where the clinic app now tests it, before those tests are removed.
"Retired" means SC-003's agreed list (the app opening without a staff password, the live screenshot saved on the
server, How it works' placeholder images and formula) or Streamlit-only mechanics with no equivalent in a stateless
web app.

## tests/test_app_pages.py (59 functions, 66 tests)

| Old test | Clinic test |
|---|---|
| test_page_renders_without_exception (8 pages) | test_clinic_routes::test_every_page_in_the_menus_is_online; test_clinic_static::test_every_rendered_page_obeys_the_policy |
| test_dashboard_lists_real_recent_sessions | test_clinic_records::test_the_dashboard_is_home_and_shows_today_and_activity |
| test_dashboard_says_when_there_are_no_sessions | test_clinic_voice_notes::test_the_dashboard_says_when_there_are_no_sessions |
| test_sessions_page_shows_event_log_and_exports | test_clinic_records::test_sessions_list_detail_and_exports |
| test_patients_page_lists_registry | test_clinic_patients_http::test_the_list_and_the_tabs |
| test_sidebar_patient_selector_lists_store_patients | test_clinic_quick_fixes::test_search_goes_straight_to_a_single_match; test_clinic_patients::test_list_rows_put_attention_first_and_discharged_last |
| test_review_page_trends_tab | test_clinic_review::test_trends_table_charts_and_first_to_latest |
| test_review_page_session_tab | test_clinic_review::test_session_review_is_saved_for_this_patients_session_only |
| test_review_page_flags_tab | test_clinic_review::test_flags_and_compare_from_the_sets |
| test_review_page_settings_gap_input | test_clinic_review::test_thresholds_store_only_what_differs_and_reset |
| test_review_page_compare_tab | test_clinic_review::test_flags_and_compare_from_the_sets |
| test_review_page_goal_form | test_clinic_review::test_a_goal_target_at_zero_is_removed |
| test_review_page_export_tab | test_clinic_review::test_export_downloads |
| test_tracker_page_roster | test_clinic_tracker::test_the_roster_shows_the_columns_and_only_the_caseload |
| test_patients_page_program_form | test_clinic_patients_http::test_program_and_questionnaires |
| test_tracker_page_adherence | test_clinic_tracker::test_adherence_states |
| test_tracker_page_queue | test_clinic_tracker::test_the_queue_links_each_item_to_where_it_is_dealt_with |
| test_tracker_page_discharged_and_patient_controls | test_clinic_tracker::test_discharged_and_reactivate; test_clinic_patients_http::test_discharge_and_reactivate |
| test_tracker_page_export | test_clinic_tracker::test_the_roster_csv |
| test_live_page_controls_come_from_the_configuration | test_clinic_live::test_switch_reset_and_target (exercise list from config.yaml) |
| test_live_page_shows_stored_summary_and_opens_the_session | test_clinic_live::test_the_socket (stop returns the summary; the page links the log) |
| test_live_page_while_playing_offers_switch_and_reset | test_clinic_live::test_switch_reset_and_target |
| test_live_page_interrupts_a_session_whose_stream_was_lost | test_clinic_live::test_a_cut_connection_resumes_and_keeps_the_count (a socket that closes interrupts the session; test_portal_ws pins the same transport) |
| test_live_page_leaves_a_session_that_is_still_finishing | test_clinic_live::test_refusals (a running session is never interrupted by another start) |
| test_live_page_screenshot_without_a_frame | Retired (SC-003): the screenshot is a browser download |
| test_live_page_screenshot_saves_the_current_frame | Retired (SC-003): the screenshot is a browser download |
| test_review_page_thresholds_editor | test_clinic_review::test_thresholds_store_only_what_differs_and_reset |
| test_tracker_adherence_states_the_threshold | test_clinic_tracker::test_adherence_states |
| test_tracker_installation_thresholds_editor | test_clinic_tracker::test_clinic_thresholds_are_read_by_all_and_changed_by_admins |
| test_review_thresholds_for_one_exercise_and_history | test_clinic_review::test_thresholds_store_only_what_differs_and_reset; src rules in test_ptlog_thresholds* |
| test_tracker_settings_shows_installation_history | test_clinic_tracker::test_clinic_thresholds_are_read_by_all_and_changed_by_admins |
| test_therapist_app_shows_only_a_sign_in_when_a_password_is_set | test_clinic_signin::test_pages_send_a_visitor_to_sign_in_and_keep_where_they_were_going |
| test_password_opens_the_app_and_sign_out_closes_it | test_clinic_signin::test_the_sign_in_form; test_sign_out_ends_the_sign_in |
| test_a_pass_from_the_front_page_opens_the_app_once | test_clinic_signin::test_the_pass_signs_in_once_and_leaves_the_address |
| test_without_a_password_the_app_opens_as_before | Retired (SC-003): now a setup message (test_clinic_signin::test_no_staff_password_shows_the_setup_message) |
| test_patients_page_issues_a_code_once_and_revokes_it | test_clinic_patients_http::test_logging_and_home_access |
| test_inbox_lists_conversations_and_the_sidebar_counts_unread | test_clinic_inbox_http::test_the_inbox_and_the_conversation_page_mark_nothing_read; test_clinic_quick_fixes::test_every_page_shows_the_needs_you_count |
| test_opening_a_thread_marks_it_read_and_a_reply_is_stored | test_clinic_inbox_http::test_the_inbox_and_the_conversation_page_mark_nothing_read (explicit read, FR-007); test_reply_warning_and_send_anyway |
| test_reply_with_identifying_text_asks_first | test_clinic_inbox_http::test_reply_warning_and_send_anyway |
| test_thread_shows_context_and_can_turn_messaging_off_and_remove | test_clinic_inbox_http::test_messaging_off_closes_the_reply_box; test_remove_a_message_leaves_a_marker |
| test_review_from_the_patient_tab | test_clinic_review::test_from_the_patient_pain_flag_and_note_removal |
| test_review_tab_plays_reviews_and_deletes_a_clip | test_clinic_review (clip routes, ownership walked in test_clinic_routes) |
| test_patients_page_sets_the_medication_list_and_the_diary_switch | test_clinic_patients_http::test_logging_and_home_access |
| test_review_from_the_patient_shows_diary_medication_and_sleep | test_clinic_review::test_every_section_renders_and_obeys_the_policy (from-patient section) |
| test_the_medication_list_does_not_follow_the_therapist_to_the_next_patient | Retired: a Streamlit widget-key bug; clinic forms are per patient address |
| test_patients_page_assigns_a_questionnaire_and_ends_it | test_clinic_patients_http::test_program_and_questionnaires |
| test_review_from_the_patient_shows_questionnaire_scores | test_clinic_review::test_questionnaire_chart_keeps_dates_and_totals_paired |
| test_a_questionnaire_score_survives_its_definition_changing | clinic.review.questionnaire_groups version_note; rules in test_ptlog_questionnaires* |
| test_tracker_queue_lists_an_overdue_questionnaire | test_clinic_tracker::test_targets_become_links (questionnaires:P); rules in test_ptlog_tracker |
| test_inbox_plays_a_voice_note_and_marks_it_heard | test_clinic_voice_notes::test_it_plays_and_is_marked_heard |
| test_inbox_deletes_a_voice_note_and_keeps_the_marker | test_clinic_voice_notes::test_delete_keeps_a_marker |
| test_inbox_says_when_writing_out_is_not_available | test_clinic_voice_notes::test_without_writing_out_it_says_so_and_the_reply_box_works |
| test_the_reply_box_still_works_beside_a_voice_note | test_clinic_voice_notes::test_without_writing_out_it_says_so_and_the_reply_box_works |
| test_inbox_shows_a_transcript_and_can_remove_its_text | test_clinic_voice_notes::test_a_transcript_shows_and_its_text_can_be_removed |
| test_inbox_shows_why_writing_out_failed | test_clinic_voice_notes::test_a_failed_writing_out_says_why |
| test_a_therapist_sees_only_their_own_caseload | test_clinic_routes::test_a_therapist_cannot_reach_another_therapists_patient (every route) |
| test_username_and_password_on_the_app_sign_in | test_clinic_signin::test_the_sign_in_form |
| test_an_admin_manages_people_but_sees_no_clinical_pages | test_clinic_routes::test_an_admin_who_is_not_a_therapist_is_refused_every_clinical_route; test_clinic_schedule_people |
| test_my_settings_saves_and_applies | test_clinic_signin::test_preferences_save_and_show_on_the_first_render |

## tests/test_app_layout.py (8)

| Old test | Clinic test |
|---|---|
| TestSidebar::test_primary_items_then_tools_and_no_emoji | test_clinic_nav (all); test_clinic_quick_fixes::test_the_top_bar_has_seven_items_and_a_search |
| TestSidebar::test_the_current_page_is_marked | test_clinic_nav::test_the_top_bar_on_a_page (aria-current) |
| TestSchedule::test_caseload_visits_with_the_request_first | test_clinic_schedule_people::test_the_schedule_order |
| TestSchedule::test_empty | test_clinic_schedule_people::test_the_schedule_page (empty sections render) |
| TestPatientTabs::test_tabs_and_metrics_without_a_key | test_clinic_assist::test_no_key_no_ai_control; test_clinic_patients_http::test_the_list_and_the_tabs |
| TestPatientTabs::test_the_ai_settings_tab_appears_with_a_key | test_clinic_assist::test_with_a_key_the_switches_and_the_summary |
| TestPatientTabs::test_messages_tab_opens_the_conversation | test_clinic_patients_http::test_the_list_and_the_tabs (Messages links the Inbox) |
| TestInbox::test_unread_sits_before_the_long_plan_column | Retired: a Streamlit table column order; the Needs you rows show the unread tag first (test_clinic_inbox_http) |

## tests/test_app_plans.py (5)

| Old test | Clinic test |
|---|---|
| TestInboxByPlan::test_one_plan_at_a_time_with_the_photo_and_the_flag | test_clinic_inbox::test_needs_you_lists_unread_by_plan_and_marks_nothing_read; test_clinic_inbox_http::test_reply_with_a_photo_as_a_form |
| TestInboxByPlan::test_a_reply_goes_into_the_chosen_plan | test_clinic_inbox_http::test_reply_warning_and_send_anyway (plan_id checked) |
| TestInboxByPlan::test_an_archived_plan_is_read_only | test_clinic_inbox_http::test_an_archived_plan_is_read_only |
| TestPlansOnThePatientPage::test_open_edit_complete_and_archive | test_clinic_patients_http::test_plans_and_the_archived_rule |
| TestAppointmentsOnThePatientPage::test_add_move_decline_and_cancel | test_clinic_patients_http::test_visits |

## tests/test_app_assist.py (9)

| Old test | Clinic test |
|---|---|
| TestNoKey::test_no_ai_control_anywhere | test_clinic_assist::test_no_key_no_ai_control; test_clinic_inbox_http::test_no_key_no_draft_button |
| TestSummaryPanel::test_summarise_save_and_the_marker | test_clinic_assist::test_with_a_key_the_switches_and_the_summary |
| TestSummaryPanel::test_unavailable | test_clinic_assist::test_citations_and_states |
| TestSummaryPanel::test_no_records | test_clinic_assist::test_citations_and_states |
| TestAISettings::test_switches_default_off_and_turn_on | test_clinic_assist::test_with_a_key_the_switches_and_the_summary |
| TestDraftReply::test_the_draft_fills_the_box_and_is_marked | test_clinic_inbox_http::test_a_draft_lands_in_the_box_and_is_never_sent |
| TestDraftReply::test_a_draft_never_follows_to_another_conversation | Retired: a draft lives in one conversation page; it can't follow (no shared session state) |
| TestDraftReply::test_withheld_and_handled_by_phone | test_clinic_inbox_http::test_a_red_flag_withholds_the_draft_and_quotes_the_words |
| TestCoachLog::test_empty_then_every_turn_read_only | test_clinic_assist::test_the_coach_log_is_read_only_and_escaped |

## tests/test_live_processor.py (8)

| Old test | Clinic test |
|---|---|
| test_frames_pass_through_until_configured, test_first_frame_starts_the_session_and_on_ended_completes_it, test_patient_is_fixed_once_the_session_exists, test_unknown_patient_reports_an_error_and_keeps_streaming, test_switch_and_reset_requests_apply_on_the_next_frame | test_clinic_live (start, frames, switch, reset, stop; unknown patient refused before any frame) |
| TestScreenshot (3) | Retired (SC-003): the screenshot is a browser download |
