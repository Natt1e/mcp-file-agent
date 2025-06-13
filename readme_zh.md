# MCP-filesystem-python
MCP官方写的filesystem的服务器是拿ts写的，我用python重写了一下，可能会有bug

## 环境配置
```
pip install "mcp[cli]" httpx
pip install mcp anthropic python-dotenv
pip install openai
```

## 运行命令
运行前首先要配置环境变量，其中包括 :
* OPENAI_API_KEY  : 调用LLM的api_key （sk-xxx）
* OPENAI_BASE_URL : 调用LLM的base_url 
* MODEL           : 使用的LLM
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