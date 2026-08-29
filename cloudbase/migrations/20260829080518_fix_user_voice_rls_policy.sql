DROP POLICY IF EXISTS user_voice_isolation ON user_voices; CREATE POLICY user_voice_owner_all ON user_voices FOR ALL USING (uid = auth.uid()) WITH CHECK (uid = auth.uid());
