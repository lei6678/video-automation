import sys
sys.path.insert(0, 'e:/video-automation/backend')

import edge_tts
from edge_tts.communicate import mkssml, TTSConfig

# 模拟 Communicate 内部的处理流程
ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN"><voice name="zh-CN-XiaoxiaoNeural">你好，<break time="300ms"/>世界！</voice></speak>'
print('原始 SSML:')
print(ssml)
print()

# 经过 patch 后的 escape
escaped = edge_tts.communicate.escape(ssml)
print('escape 后:')
print(escaped)
print()

# mkssml 包裹后的最终内容
tc = TTSConfig('zh-CN-XiaoxiaoNeural', '+0%', '+0%', '+0Hz', 'SentenceBoundary')
final = mkssml(tc, escaped)
print('mkssml 最终结果:')
print(final)
print()
print('包含 <break ?', '<break' in final)
print('包含 &lt;break ?', '&lt;break' in final)
