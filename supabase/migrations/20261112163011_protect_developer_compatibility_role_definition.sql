UPDATE public.role_definitions
SET is_system = true
WHERE role_key = 'developer' AND is_system = false;
