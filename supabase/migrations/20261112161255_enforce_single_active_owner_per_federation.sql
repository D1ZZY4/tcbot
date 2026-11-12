CREATE UNIQUE INDEX uq_role_assignments_single_active_owner_per_federation
ON public.role_assignments (federation_id)
WHERE role_key = 'owner' AND status = 'active';
