-- 测试数据（初始化后插入）

-- 默认用户
INSERT INTO users (username, display_name) VALUES ('songmiao', '宋淼');

-- 预置音色（豆包大模型音色）
INSERT INTO voices (speaker_id, name, type, provider, gender, note) VALUES
('zh_female_yingtaowanzi_uranus_bigtts', '樱桃丸子', 'preset', 'volc',    'female', '豆包同款'),
('zh_male_silang_uranus_bigtts',         '四郎',     'preset', 'volc',    'male',   '豆包同款'),
('zh_male_qingcang_uranus_bigtts',       '擎苍',     'preset', 'volc',    'male',   '番茄小说同款');

-- 克隆音色（声音复刻 2.0）
INSERT INTO voices (speaker_id, name, type, provider, gender, note) VALUES
('S_7PtM1phd2', '我的声音', 'clone', 'volc', 'male', '参考音频：标准录音 3.mp3');

-- 设计音色（MiniMax Voice Design）
INSERT INTO voices (speaker_id, name, type, provider, gender, note) VALUES
('ttv-voice-2026082710331426-UpOQXpI8', '睡前故事姐姐', 'design', 'minimax', 'female', '温柔的年轻女声，讲睡前故事的姐姐');

-- 示例任务
INSERT INTO tasks (task_id, text_len, narrator, use_bgm, status, duration_s) VALUES
('a959c474d024', 858, 'S_7PtM1phd2', 1, 'done', 198.2),
('2a80ba2abd81', 741, 'S_7PtM1phd2', 1, 'done', 198.2);

-- 示例作品
INSERT INTO works (task_id, title, audio_path, duration_s, bgm_name) VALUES
('a959c474d024', '末班车（广播剧）', 'outputs/m2/bus_final.mp3', 198.2, 'neutral.mp3'),
('2a80ba2abd81', '信号（科幻短篇）', 'outputs/m1/final_1000.mp3', 208.6, 'tense.mp3');
