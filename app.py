from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-ef3a78aa5c3c473ab154a1be2a9cbd7f"),
    base_url="https://api.deepseek.com"
)

# 全局对话历史存储
conversations = {}

# 用户状态跟踪
user_states = {}


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_id = data.get('user_id', 'default_user')
    user_input = data['message'].strip()

    # 初始化用户状态
    if user_id not in user_states:
        user_states[user_id] = {
            'step': 'ask_scenario',  # 步骤：ask_scenario -> ask_question -> answer
            'scenario': None,
            'question': None,
            'confirmed_scenario': False,  # 标记场景是否已确认
            'safety_rules': None  # 存储安全规则
        }

    current_state = user_states[user_id]

    # 检查是否要退出
    if user_input.lower() in ["退出", "exit", "quit"]:
        return jsonify({"response": "对话结束，再见！", "done": True})

    # 检查是否要更改场景
    if user_input.lower() in ["更改场景", "change scenario"]:
        current_state['step'] = 'ask_scenario'
        current_state['scenario'] = None
        current_state['confirmed_scenario'] = False
        current_state['safety_rules'] = None
        return jsonify({
            "response": "好的，请告诉我您新的使用场景是什么？",
            "done": False,
            "reset": True
        })

    # 第一步：询问场景
    if current_state['step'] == 'ask_scenario':
        # 初始化对话历史
        if user_id not in conversations:
            conversations[user_id] = [
                {"role": "system", "content": "请先询问用户的使用场景，然后根据场景制定安全规则，最后回答问题。"}
            ]

        # 如果是第一次询问场景
        if not current_state['scenario']:
            current_state['scenario'] = user_input
            return jsonify({
                "response": f"您当前的使用场景是: {user_input}\n\n请确认这是否正确？(回答'是'或'否')",
                "done": False
            })
        else:
            # 用户确认场景
            if user_input.lower() in ["是", "yes", "对"]:
                current_state['confirmed_scenario'] = True
                current_state['step'] = 'generate_rules'
                conversations[user_id].append({"role": "user", "content": f"确认场景: {current_state['scenario']}"})

                # 生成安全规则
                try:
                    rules_prompt = (
                        f"根据以下教育场景生成详细的安全规则和注意事项:\n"
                        f"场景: {current_state['scenario']}\n\n"
                        "请以清晰条理的方式列出规则，每条规则前用•标记。"
                    )

                    rules_response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "你是一个教育安全专家，擅长为不同教育场景制定安全规则。"},
                            {"role": "user", "content": rules_prompt}
                        ],
                        max_tokens=1024,
                        stream=False
                    )

                    current_state['safety_rules'] = rules_response.choices[0].message.content

                    return jsonify({
                        "response": f"已确认您的使用场景为: {current_state['scenario']}\n\n我已为您生成以下安全规则:",
                        "rules": current_state['safety_rules'],
                        "next_step": "请提出您的具体问题:",
                        "done": False
                    })

                except Exception as e:
                    return jsonify({"error": f"生成安全规则时发生错误: {e}"}), 500

            else:
                # 用户否认场景，重新询问
                current_state['scenario'] = None
                return jsonify({
                    "response": "请重新描述您的使用场景:",
                    "done": False
                })

    # 第二步：生成安全规则后等待问题
    elif current_state['step'] == 'generate_rules':
        current_state['step'] = 'ask_question'
        current_state['question'] = user_input
        conversations[user_id].append({"role": "user", "content": f"问题: {user_input}"})

        # 准备完整的提示
        full_prompt = (
            f"用户使用场景: {current_state['scenario']}\n"
            f"已制定的安全规则: {current_state['safety_rules']}\n"
            f"用户问题: {current_state['question']}\n\n"
            "请严格遵守上述安全规则回答问题。"
        )

        # 添加到对话历史
        conversations[user_id].append({"role": "user", "content": full_prompt})

        try:
            # 调用 API
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=conversations[user_id],
                max_tokens=2048,
                stream=False
            )

            # 获取 AI 回复
            ai_response = response.choices[0].message.content

            # 添加到对话历史
            conversations[user_id].append({"role": "assistant", "content": ai_response})

            # 重置问题状态，保持场景不变
            current_state['question'] = None
            current_state['step'] = 'ask_question'

            return jsonify({
                "response": ai_response,
                "rules": current_state['safety_rules'],
                "scenario": current_state['scenario'],
                "done": False
            })

        except Exception as e:
            return jsonify({"error": f"发生错误: {e}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)