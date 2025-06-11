# 总览
这是一个非常简单的 可以操作文件的 基于MCP的 用python编写的 agent

## 环境配置
```
pip install "mcp[cli]" httpx
pip install mcp anthropic python-dotenv
pip install openai
```

## 运行命令
运行前首先要配置环境变量，其中包括 :
OPENAI_API_KEY  : 调用LLM的api_key （sk-xxx）
OPENAI_BASE_URL : 调用LLM的base_url 
MODEL           : 使用的LLM
创建.env文件，向其中写入这三项即可 
```
OPENAI_API_KEY=sk-xx
OPENAI_BASE_URL=https://api.xxx/v1
MODEL=gpt-4o-mini
```
直接运行即可:
```
python mcpOpenaiClientClient.py filesystemServer.py <target_dir>
```