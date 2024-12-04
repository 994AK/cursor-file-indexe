# 前端项目依赖分析工具

一个用于分析前端项目依赖关系并生成结构化报告的 Python 工具。该工具可以帮助 AI 理解代码上下文并协助项目分析。

## 主要功能

- 递归扫描项目目录
- 支持多种导入语句分析：
  - ES6 导入语句
  - require 语句
  - 动态导入
  - 类型导入
- 别名路径解析（例如：@/components）
- 文件类型和用途识别
- 依赖关系分类：
  - 组件依赖
  - Hooks 依赖
  - 工具函数
  - 类型定义
  - 样式文件
  - 外部依赖

## 安装方式

### 方式一：直接安装（不推荐）

1. 确保系统已安装 Python 3.7+ 和 pip
2. 直接安装依赖：

```bash
pip install pathlib>=2.3.7 rich>=10.0.0 typing-extensions>=4.7.0
```

### 方式二：虚拟环境安装（推荐）

#### 1. 安装虚拟环境工具

Windows 系统：

```bash
pip install virtualenv
```

macOS/Linux 系统：

```bash
pip3 install virtualenv
```

#### 2. 创建项目目录

```bash
mkdir frontend-analyzer
cd frontend-analyzer
```

#### 3. 创建并激活虚拟环境

Windows 系统：

```bash
# 创建虚拟环境
python -m venv venv
# 激活虚拟环境
.\venv\Scripts\activate
```

macOS/Linux 系统：

```bash
# 创建虚拟环境
python3 -m venv venv
# 激活虚拟环境
source venv/bin/activate
```

#### 4. 安装项目依赖

```bash
pip install -r requirements.txt
```

#### 5. 验证安装

```bash
# 进入Python交互环境
python
>>> from rich.console import Console
>>> console = Console()
>>> console.print("[bold green]安装成功！[/]")
```

如果看到绿色的"安装成功！"文字，说明环境配置完成。

### 方式三：Conda 环境安装

1. 安装 Anaconda 或 Miniconda
   从官网下载并安装：https://www.anaconda.com/products/distribution

2. 创建新的 Conda 环境

```bash
# 创建Python 3.7环境
conda create -n frontend-analyzer python=3.7
# 激活环境
conda activate frontend-analyzer
```

3. 安装依赖

```bash
pip install -r requirements.txt
```

### 方式四：Docker 安装（开发中）

即将支持 Docker 方式安装，敬请期待。

## 配置说明

在项目根目录创建 `config.json` 文件：

```json
{
  "project_path": "/你的前端项目路径/src",
  "alias_mappings": {
    "@": "src",
    "@components": "src/components",
    "@utils": "src/utils"
  },
  "ignore_patterns": [
    "node_modules",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".DS_Store"
  ]
}
```

### 配置选项说明

- `project_path`：要分析的前端项目路径（支持绝对路径或相对路径）
- `alias_mappings`：项目中使用的路径别名映射配置
- `ignore_patterns`：需要忽略的目录或文件模式
- `analyze_mode`：分析模式，支持 "deep"（深度分析）和 "simple"（简单分析）
- `max_depth`：最大分析深度，默认为 5 层

如果未提供配置文件，工具将使用以下默认配置：

- 使用当前目录作为项目路径
- 不使用别名映射
- 使用默认的忽略模式

## 使用方法

在你的前端项目目录下运行分析器：

```bash
python src/analyzer.py
```

工具将执行以下步骤：

1. 读取配置文件（如果存在）
2. 扫描指定的项目目录
3. 分析依赖关系
4. 生成结构化报告

## 输出格式

工具将生成一个树状结构的报告，显示：

- 文件依赖关系
- 组件之间的关系
- 依赖统计信息
- 文件分类信息

输出示例：

```
📁 项目依赖关系 (/你的前端项目路径/src)
├── src/components/UserProfile/index.tsx
│   ├── 组件依赖
│   │   ├── @/components/common/Avatar
│   │   └── @/components/common/Button
│   ├── Hooks依赖
│   │   └── @/hooks/useUser
│   ├── 工具函数
│   │   └── @/utils/date
│   └── 外部依赖
│       ├── react
│       └── axios
```

## 环境要求

- Python 3.7 或更高版本
- pip 20.0.0 或更高版本
- 支持的操作系统：
  - Windows 10/11
  - macOS 10.15+
  - Linux (Ubuntu 18.04+, CentOS 7+)
- 内存要求：至少 2GB 可用内存
- 磁盘空间：至少 500MB 可用空间

## 支持的文件类型

- 组件文件：.jsx, .tsx, .vue
- 脚本文件：.js, .ts
- 样式文件：.css, .scss, .less, .sass
- 类型文件：.d.ts

## 使用说明

### 1. 环境准备

- 确保安装了 Python 3.7 或更高版本
- 安装了 pip（Python 包管理器）

### 2. 详细安装步骤

#### 2.1 创建并激活虚拟环境（推荐）

Windows 系统：

```bash
python -m venv venv
.\venv\Scripts\activate
```

macOS/Linux 系统：

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 2.2 安装项目依赖

```bash
pip install -r requirements.txt
```

### 3. 常见问题解决

#### 依赖安装问题

如果安装依赖时遇到问题，可以尝试：

```bash
# 更新pip
python -m pip install --upgrade pip

# 单独安装依赖
pip install pathlib>=2.3.7
pip install rich>=10.0.0
pip install typing-extensions>=4.7.0
```

#### 权限问题

- Windows：以管理员身份运行命令提示符
- Linux/macOS：使用 sudo 运行安装命令

#### Python 版本问题

- 推荐使用 pyenv 管理多个 Python 版本
- 确保使用 Python 3.7 或更高版本

## 特别说明

- 支持自定义配置文件来设置分析路径
- 自动处理各种文件编码问题
- 可配置忽略特定目录
- 支持项目中的路径别名解析
- 提供详细的控制台输出信息

## 参与贡献

欢迎提交问题和功能改进建议！

## 开源协议

MIT License
