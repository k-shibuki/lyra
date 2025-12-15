-- Migration: Add Wayback Machine fallback tracking columns
-- Created: 2025-01-15
-- 
-- Adds columns to track Wayback Machine fallback success/failure counts
-- for domain-level statistics and adaptive fallback decisions.

ALTER TABLE domains ADD COLUMN wayback_success_count INTEGER DEFAULT 0;
ALTER TABLE domains ADD COLUMN wayback_failure_count INTEGER DEFAULT 0;

