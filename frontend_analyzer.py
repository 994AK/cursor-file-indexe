#!/usr/bin/env python3
"""
Frontend Project Dependency Analyzer
Analyzes frontend project dependencies and generates structured reports.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Union, DefaultDict, Tuple, Any
from dataclasses import dataclass, field
from rich.console import Console
from rich.tree import Tree
from collections import defaultdict
import fnmatch
from functools import lru_cache
import hashlib
from datetime import datetime
import argparse

@dataclass
class SearchIndex:
    """File search index"""
    file_index: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))  # 文件名 -> 路径集合
    import_index: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))  # 导入名 -> 文件路径集合
    extension_index: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))  # 扩展名 -> 文件路径集合

@dataclass
class Config:
    """Configuration for the analyzer"""
    project_path: Path
    alias_mappings: Dict[str, str]
    ignore_patterns: Set[str]
    analyze_mode: str = "deep"  # 'deep' or 'shallow'
    max_depth: int = 5
    index_extensions: Dict[str, Dict[str, Union[List[str], List[str]]]] = field(default_factory=lambda: {
        "vue": {
            "extensions": [".vue"],
            "patterns": [
                r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                r'require\([\'"]([^\'"]+)[\'"]\)',
                r'import\([\'"]([^\'"]+)[\'"]\)',
                r'import\s+type\s+{[^}]*}\s+from\s+[\'"]([^\'"]+)[\'"]'
            ]
        },
        "typescript": {
            "extensions": [".ts", ".tsx"],
            "patterns": [
                r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                r'import\s+type\s+{[^}]*}\s+from\s+[\'"]([^\'"]+)[\'"]'
            ]
        },
        "javascript": {
            "extensions": [".js", ".jsx"],
            "patterns": [
                r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                r'require\([\'"]([^\'"]+)[\'"]\)'
            ]
        }
    })

    @staticmethod
    def default_index_extensions():
        """Default index extensions configuration"""
        return {
            "vue": {
                "extensions": [".vue"],
                "patterns": [
                    r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                    r'require\([\'"]([^\'"]+)[\'"]\)',
                    r'import\([\'"]([^\'"]+)[\'"]\)',
                    r'import\s+type\s+{[^}]*}\s+from\s+[\'"]([^\'"]+)[\'"]'
                ]
            },
            "typescript": {
                "extensions": [".ts", ".tsx"],
                "patterns": [
                    r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                    r'import\s+type\s+{[^}]*}\s+from\s+[\'"]([^\'"]+)[\'"]'
                ]
            },
            "javascript": {
                "extensions": [".js", ".jsx"],
                "patterns": [
                    r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                    r'require\([\'"]([^\'"]+)[\'"]\)'
                ]
            }
        }

    @classmethod
    def load(cls, config_path: Union[str, Path] = "config.json") -> 'Config':
        """Load configuration from a JSON file"""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                return cls(
                    project_path=Path(os.path.expanduser(data['project_path'])),
                    alias_mappings=data.get('alias_mappings', {}),
                    ignore_patterns=set(data.get('ignore_patterns', [])),
                    analyze_mode=data.get('analyze_mode', 'deep'),
                    max_depth=data.get('max_depth', 5),
                    index_extensions=data.get('index_extensions', cls.default_index_extensions())
                )
        except FileNotFoundError:
            console = Console()
            console.print(f"[yellow]Warning: Config file {config_path} not found. Using default configuration.[/yellow]")
            return cls(
                project_path=Path.cwd(),
                alias_mappings={},
                ignore_patterns={'node_modules', 'dist', 'build', '.git', '__pycache__', '.DS_Store', '.history'},
                analyze_mode='deep',
                max_depth=5
            )

@dataclass
class DependencyInfo:
    """Stores dependency information for a file"""
    components: Dict[str, 'DependencyInfo'] = field(default_factory=dict)  # Changed from Set to Dict for nested deps
    hooks: Set[str] = field(default_factory=set)
    utils: Set[str] = field(default_factory=set)
    types: Set[str] = field(default_factory=set)
    styles: Set[str] = field(default_factory=set)
    external: Set[str] = field(default_factory=set)
    api: Set[str] = field(default_factory=set)
    depth: int = 0
    parent: Optional[str] = None

@dataclass
class FileInfo:
    """Stores file information and its dependencies"""
    path: Path
    file_type: str
    dependencies: DependencyInfo = field(default_factory=DependencyInfo)
    analyzed: bool = False

@dataclass
class MerkleNode:
    """Merkle树节点"""
    hash: str
    type: str  # 'file', 'component', 'api', 'hook', 'util', 'external'
    name: str
    children: List['MerkleNode'] = field(default_factory=list)
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # 存储额外的元数据
    imports: List[str] = field(default_factory=list)  # 存储导入语句
    exports: List[str] = field(default_factory=list)  # 存储导出内容
    dependencies_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))  # 各类型依赖数量统计

class DependencyMerkleTree:
    """依赖关系的Merkle树实现"""
    
    def __init__(self):
        self.nodes: Dict[str, MerkleNode] = {}
    
    def _calculate_hash(self, content: str) -> str:
        """计算内容的哈希值"""
        return hashlib.sha256(content.encode()).hexdigest()[:8]  # 使用短哈希以提高可读性
    
    def _extract_file_info(self, file_path: Path) -> Dict[str, Any]:
        """提取文件的详细信息"""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # 提取导入语句
            imports = re.findall(r'import\s+.*?[\'"]([^\'"]+)[\'"]', content)
            
            # 提取导出语句
            exports = re.findall(r'export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)', content)
            
            # 统计代码行数（排除空行和注释）
            lines = content.split('\n')
            code_lines = len([line for line in lines if line.strip() and not line.strip().startswith('//')])
            
            # 检查是否包含特定功能
            has_state_management = bool(re.search(r'useState|useReducer|createStore|Vuex|Pinia', content))
            has_routing = bool(re.search(r'useRouter|useRoute|Router|createRouter', content))
            has_api_calls = bool(re.search(r'fetch|axios|useQuery|useMutation', content))
            has_form_handling = bool(re.search(r'useForm|v-model|formData|handleSubmit', content))
            
            return {
                'imports': imports,
                'exports': exports,
                'code_lines': code_lines,
                'features': {
                    'state_management': has_state_management,
                    'routing': has_routing,
                    'api_calls': has_api_calls,
                    'form_handling': has_form_handling
                }
            }
        except Exception:
            return {}
    
    def _create_node(self, name: str, type: str, content: Optional[str] = None, file_path: Optional[Path] = None) -> MerkleNode:
        """创建或获取节点"""
        if name in self.nodes:
            return self.nodes[name]
            
        node_content = content or name
        node_hash = self._calculate_hash(f"{type}:{node_content}")
        
        # 初始化节点
        node = MerkleNode(
            hash=node_hash,
            type=type,
            name=name,
            content=content,
            metadata={},
            imports=[],
            exports=[],
            dependencies_count=defaultdict(int)
        )
        
        # 如果提供了文件路径，提取更多信息
        if file_path and file_path.exists():
            file_info = self._extract_file_info(file_path)
            node.metadata.update(file_info)
            node.imports.extend(file_info.get('imports', []))
            node.exports.extend(file_info.get('exports', []))
        
        self.nodes[name] = node
        return node
    
    def build_from_dependencies(self, deps: DependencyInfo, file_path: str) -> MerkleNode:
        """从依赖信息构建Merkle树"""
        root = self._create_node(file_path, 'file', file_path=Path(file_path))
        
        # 统计依赖数量
        root.dependencies_count.update({
            'components': len(deps.components),
            'api': len(deps.api),
            'hooks': len(deps.hooks),
            'utils': len(deps.utils),
            'external': len(deps.external)
        })
        
        # 添加组件依赖
        for comp_name in deps.components:
            comp_node = self._create_node(comp_name, 'component', file_path=Path(comp_name))
            root.children.append(comp_node)
        
        # 添加API依赖
        for api_name in deps.api:
            api_node = self._create_node(api_name, 'api', file_path=Path(api_name))
            root.children.append(api_node)
        
        # 添加Hooks依赖
        for hook_name in deps.hooks:
            hook_node = self._create_node(hook_name, 'hook', file_path=Path(hook_name))
            root.children.append(hook_node)
        
        # 添加工具依赖
        for util_name in deps.utils:
            util_node = self._create_node(util_name, 'util', file_path=Path(util_name))
            root.children.append(util_node)
        
        # 添加外部依赖
        for ext_name in deps.external:
            ext_node = self._create_node(ext_name, 'external')
            root.children.append(ext_node)
        
        return root
    
    def generate_ai_readable_format(self, root: MerkleNode, indent: int = 0) -> str:
        """生成AI友好的可读格式"""
        result = []
        prefix = "  " * indent
        
        # 添加节点基本信息
        node_info = f"{prefix}[{root.type}:{root.hash}] {root.name}"
        result.append(node_info)
        
        # 添加元数据信息
        if root.metadata:
            meta_prefix = "  " * (indent + 1)
            if 'code_lines' in root.metadata:
                result.append(f"{meta_prefix}📊 代码行数: {root.metadata['code_lines']}")
            
            if 'features' in root.metadata:
                features = root.metadata['features']
                feature_icons = {
                    'state_management': '🔄 状态管理',
                    'routing': '🛣️ 路由处理',
                    'api_calls': '🌐 API调用',
                    'form_handling': '📝 表单处理'
                }
                active_features = [f"{icon}" for key, icon in feature_icons.items() if features.get(key)]
                if active_features:
                    result.append(f"{meta_prefix}✨ 功能特性: {' '.join(active_features)}")
        
        # 添加依赖统计
        if root.dependencies_count:
            stats_prefix = "  " * (indent + 1)
            stats = [f"{k}: {v}" for k, v in root.dependencies_count.items() if v > 0]
            if stats:
                result.append(f"{stats_prefix}📈 依赖统计: {', '.join(stats)}")
        
        # 添加导入导出信息
        if root.imports:
            imports_prefix = "  " * (indent + 1)
            result.append(f"{imports_prefix}📥 导入: {', '.join(root.imports[:3])}{'...' if len(root.imports) > 3 else ''}")
        if root.exports:
            exports_prefix = "  " * (indent + 1)
            result.append(f"{exports_prefix}📤 导出: {', '.join(root.exports)}")
        
        # 递归处理子节点
        for child in root.children:
            result.append(self.generate_ai_readable_format(child, indent + 1))
        
        return "\n".join(result)

    def export_report(self, root: MerkleNode, file_path: str, prompt: str = "", focus_points: List[str] = None) -> str:
        """导出分析报告到文件"""
        content = []
        
        # 添加分隔线
        content.append("-" * 20)
        
        # 添加AI提示词
        if prompt:
            content.append(prompt)
            
        if focus_points:
            content.append("\n重点关注领域:")
            for point in focus_points:
                content.append(f"• {point}")
        
        # 添加Merkle树分析
        content.append("\n以下是Merkle树分析:\n")
        content.append("Merkle树分析:")
        content.append(self.generate_ai_readable_format(root))
        
        # 添加底部分隔线
        content.append("-" * 20)
        
        return "\n".join(content)

class FrontendAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        self.files: Dict[str, FileInfo] = {}
        self.dependency_graph: DefaultDict[str, Set[str]] = defaultdict(set)
        self.console = Console()
        self.search_index = SearchIndex()
        self.merkle_tree = DependencyMerkleTree()
        
        # 创建reports目录
        self.reports_dir = Path("reports")
        self.reports_dir.mkdir(exist_ok=True)
        
        # 加载提示词配置
        self.prompts = self._load_prompts()
        
        # 从配置文件加载导入模式
        self.import_patterns = {}
        if hasattr(config, 'index_extensions'):
            for lang, lang_config in config.index_extensions.items():
                for pattern in lang_config['patterns']:
                    self.import_patterns[f"{lang}_{pattern[:10]}"] = pattern
        else:
            # 默认的导入模式作为后备
            self.import_patterns = {
                'es6': r'import\s+(?:{[^}]*}|\*\s+as\s+\w+|\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
                'require': r'require\([\'"]([^\'"]+)[\'"]\)',
                'dynamic': r'import\([\'"]([^\'"]+)[\'"]\)',
                'type': r'import\s+type\s+{[^}]*}\s+from\s+[\'"]([^\'"]+)[\'"]'
            }

    def _load_prompts(self) -> Dict:
        """加载提示词配置"""
        try:
            with open('prompts.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.console.print(f"[yellow]Warning: Failed to load prompts.json: {e}[/yellow]")
            return {"commit_types": {}}

    def generate_report(self, commit_type: str = "feat"):
        """生成并打印分析报告"""
        if not self.files:
            self.console.print("[yellow]还没有找到任何文件呢~[/yellow]")
            return
        
        # 获取对应类型的提示词
        prompt_config = self.prompts.get("commit_types", {}).get(commit_type, {})
        
        # 获取分析的文件
        try:
            target_file = Path(self.config.project_path)
            if target_file.is_file():
                rel_path = target_file.relative_to(target_file.parent.parent.parent)
                
                # 生成Merkle树
                merkle_root = None
                for file_path, file_info in self.files.items():
                    if str(rel_path) in file_path:
                        merkle_root = self.merkle_tree.build_from_dependencies(file_info.dependencies, file_path)
                        break
                
                if merkle_root:
                    # 导出报告到文件
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    file_name = target_file.name.replace('.', '_')
                    report_file = self.reports_dir / f"report_{timestamp}_{commit_type}_{file_name}.txt"
                    
                    report_content = self.merkle_tree.export_report(
                        merkle_root, 
                        str(target_file),
                        prompt_config.get('prompt', ''),
                        prompt_config.get('focus', [])
                    )
                    report_file.write_text(report_content, encoding='utf-8')
        
        except Exception as e:
            self.console.print(f"[red]抱歉，出了点小问题: {e}[/red]")
            return

    def _should_ignore(self, path: Path) -> bool:
        """检查是否应该忽略该文件"""
        return any(part in self.config.ignore_patterns for part in path.parts)
    
    def _determine_file_type(self, file_path: Path) -> Optional[str]:
        """根据文件路径和扩展名确定文件类型"""
        suffix = file_path.suffix
        
        # 从配置中获取文件类型
        for lang, lang_config in self.config.index_extensions.items():
            if suffix in lang_config['extensions']:
                return lang
                
        return None
    
    def _extract_dependencies(self, content: str, deps: DependencyInfo):
        """从文件内容中提取所有依赖"""
        for pattern_name, pattern in self.import_patterns.items():
            matches = re.finditer(pattern, content)
            for match in matches:
                import_path = match.group(1)
                self._categorize_dependency(import_path, deps)
    
    def _categorize_dependency(self, import_path: str, deps: DependencyInfo):
        """根据导入路径对依赖进行分类"""
        # 处理以 @ 开头的别名导入
        if import_path.startswith('@/'):
            parts = import_path.split('/')
            if len(parts) > 1:
                category = parts[1]  # 获取 @/ 后的类别
                if category == 'components':
                    deps.components[import_path] = DependencyInfo(depth=deps.depth + 1, parent=import_path)
                elif category == 'hooks':
                    deps.hooks.add(import_path)
                elif category == 'utils':
                    deps.utils.add(import_path)
                elif category == 'types':
                    deps.types.add(import_path)
                elif category == 'api':
                    deps.api.add(import_path)
                elif category.endswith(('.css', '.scss', '.less', '.sass')):
                    deps.styles.add(import_path)
                else:
                    # 默认添加到工具类
                    deps.utils.add(import_path)
            return
        
        # 处理相对路径和其他情况
        if 'components' in import_path:
            deps.components[import_path] = DependencyInfo(depth=deps.depth + 1, parent=import_path)
        elif 'hooks' in import_path:
            deps.hooks.add(import_path)
        elif 'utils' in import_path:
            deps.utils.add(import_path)
        elif 'types' in import_path or import_path.endswith('.d.ts'):
            deps.types.add(import_path)
        elif 'api' in import_path:
            deps.api.add(import_path)
        elif import_path.endswith(('.css', '.scss', '.less', '.sass')):
            deps.styles.add(import_path)
        elif not any(import_path.startswith(p) for p in ['/', '.', '@']):
            deps.external.add(import_path)
        else:
            # 默认添加到工具类
            deps.utils.add(import_path)
    
    def _process_file(self, file_path: Path, depth: int = 0):
        """处理单个文件并提取其依赖"""
        try:
            relative_path = file_path.relative_to(self.config.project_path.parent.parent.parent)
            if self._should_ignore(file_path):
                return
            
            file_type = self._determine_file_type(file_path)
            if not file_type:
                return
                
            file_info = FileInfo(path=relative_path, file_type=file_type)
            content = file_path.read_text(encoding='utf-8')
            
            deps = DependencyInfo(depth=depth)
            self._extract_dependencies(content, deps)
            file_info.dependencies = deps
            file_info.analyzed = True
            
            self.files[str(relative_path)] = file_info
            
        except Exception as e:
            self.console.print(f"[red]Error processing {file_path}: {e}[/red]")
    
    def analyze_file(self, file_path: Union[str, Path], depth: int = 0):
        """分析特定文件及其依赖"""
        if depth > self.config.max_depth:
            return
        
        file_path = Path(file_path)
        if not file_path.exists():
            self.console.print(f"[red]抱歉，找不到文件: {file_path}[/red]")
            return
        
        # 静默处理文件
        self._process_file(file_path, depth)
        
        if self.config.analyze_mode == "deep":
            self._analyze_dependencies(file_path, depth + 1)
    
    def _analyze_dependencies(self, file_path: Path, depth: int):
        """递归分析文件的依赖"""
        try:
            file_key = str(file_path.relative_to(self.config.project_path.parent.parent.parent))
        except ValueError:
            file_key = str(file_path)
            
        if file_key not in self.files:
            return
        
        file_info = self.files[file_key]
        deps = file_info.dependencies
        
        # 分析组件依赖
        for comp_path, comp_dep in deps.components.items():
            resolved_path = self._resolve_dependency_path(comp_path)
            if resolved_path:
                self.dependency_graph[file_key].add(str(resolved_path))
                if not self._is_analyzed(resolved_path):
                    self.analyze_file(resolved_path, depth)
        
        # 分析其他依赖（hooks, utils等）
        for dep_set in [deps.hooks, deps.utils]:
            for dep_path in dep_set:
                resolved_path = self._resolve_dependency_path(dep_path)
                if resolved_path:
                    self.dependency_graph[file_key].add(str(resolved_path))
                    if not self._is_analyzed(resolved_path):
                        self.analyze_file(resolved_path, depth)
    
    def _is_analyzed(self, file_path: Path) -> bool:
        """检查文件是否已经被分析过"""
        try:
            relative_path = str(file_path.relative_to(self.config.project_path.parent.parent.parent))
            return relative_path in self.files and self.files[relative_path].analyzed
        except ValueError:
            return False
    
    def _resolve_dependency_path(self, import_path: str) -> Optional[Path]:
        """解析依赖路径"""
        project_root = self.config.project_path.parent.parent.parent
        current_dir = self.config.project_path.parent
        
        # 1. 处理相对路径
        if import_path.startswith('./') or import_path.startswith('../'):
            resolved_path = (current_dir / import_path).resolve()
            if resolved_path.exists():
                return resolved_path
            
            # 尝试添加不同的扩展名
            for ext in ['.tsx', '.jsx', '.ts', '.js', '.vue', '/index.tsx', '/index.jsx', '/index.ts', '/index.js', '/index.vue']:
                test_path = resolved_path.with_suffix(ext) if not ext.startswith('/') else Path(str(resolved_path) + ext)
                if test_path.exists():
                    return test_path
        
        # 2. 处理别名路径
        if import_path.startswith('@/'):
            # 如果配置中有 "@": "src" 的映射
            if "@" in self.config.alias_mappings:
                # 直接将 @/ 替换为 src/
                normalized_path = import_path.replace('@/', f"{self.config.alias_mappings['@']}/", 1)
                full_path = project_root / normalized_path
                
                # 检查路径是否存在
                if full_path.exists():
                    return full_path
                
                # 尝试不同的扩展名
                for ext in ['.tsx', '.jsx', '.ts', '.js', '.vue', '/index.tsx', '/index.jsx', '/index.ts', '/index.js', '/index.vue']:
                    test_path = full_path.with_suffix(ext) if not ext.startswith('/') else Path(str(full_path) + ext)
                    if test_path.exists():
                        return test_path
        
        # 3. 检查导入索引
        if import_path in self.search_index.import_index:
            paths = self.search_index.import_index[import_path]
            if paths:
                return project_root / next(iter(paths))
        
        # 4. 智能查找
        base_name = os.path.basename(import_path)
        if base_name:
            # 移除可能的扩展名
            base_name = os.path.splitext(base_name)[0]
            found_path = self._find_file(base_name, current_dir)
            if found_path:
                return found_path
        
        # 5. 尝试不同的扩展名
        base_path = project_root / import_path.lstrip('/')
        for ext in ['.tsx', '.jsx', '.ts', '.js', '.vue', '/index.tsx', '/index.jsx', '/index.ts', '/index.js', '/index.vue']:
            full_path = base_path.with_suffix(ext) if not ext.startswith('/') else Path(str(base_path) + ext)
            if full_path.exists():
                return full_path
            
            # 额外检查相对于当前目录的路径
            current_full_path = (current_dir / import_path).with_suffix(ext) if not ext.startswith('/') else Path(str(current_dir / import_path) + ext)
            if current_full_path.exists():
                return current_full_path
        
        return None
    
    def _find_file(self, name: str, current_dir: Optional[Path] = None) -> Optional[Path]:
        """智能文件查找"""
        project_root = self.config.project_path.parent.parent.parent
        
        # 1. 检查索引中的精确匹配
        if name in self.search_index.file_index:
            paths = self.search_index.file_index[name]
            if len(paths) == 1:
                return project_root / next(iter(paths))
            elif current_dir:
                # 如果有多个匹配，优先选择离当前目录最近的
                return min(
                    (project_root / path for path in paths),
                    key=lambda p: len(set(p.parts) ^ set(current_dir.parts))
                )
        
        # 2. 尝试模糊匹配
        for pattern in [f"*{name}*", f"*{name}", f"{name}*"]:
            matches = set()
            for filename, paths in self.search_index.file_index.items():
                if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    matches.update(paths)
            
            if matches:
                if len(matches) == 1:
                    return project_root / next(iter(matches))
                elif current_dir:
                    return min(
                        (project_root / path for path in matches),
                        key=lambda p: len(set(p.parts) ^ set(current_dir.parts))
                    )
        
        # 3. 在当前目录中搜索
        if current_dir:
            for file_path in current_dir.rglob(f"*{name}*"):
                if file_path.is_file() and not self._should_ignore(file_path):
                    return file_path
        
        return None

def display_menu(prompts: Dict) -> str:
    """显示交互式菜单"""
    console = Console()
    console.print("\n[bold magenta]✨ 欢迎使用前端小助手 ✨[/bold magenta]")
    console.print("[bold magenta]让我们一起来分析代码吧~ [/bold magenta]\n")
    
    # 显示所有选项
    for i, (type_key, type_info) in enumerate(prompts['commit_types'].items(), 1):
        console.print(f"[green]{i}.[/green] {type_info['title']} [cyan]({type_key})[/cyan]")
    
    console.print("\n[yellow]请选择分析类型哦~ (输入数字)[/yellow]")
    
    while True:
        try:
            choice = int(input("➜ ").strip())
            if 1 <= choice <= len(prompts['commit_types']):
                return list(prompts['commit_types'].keys())[choice - 1]
            else:
                console.print("[red]哎呀，这个数字不对呢，请重新选择~[/red]")
        except ValueError:
            console.print("[red]需要输入数字啦，让我们重新来过~[/red]")

def main():
    """Main entry point"""
    console = Console()
    
    try:
        config = Config.load()
        analyzer = FrontendAnalyzer(config)
        
        # 加载提示词配置
        try:
            with open('prompts.json', 'r', encoding='utf-8') as f:
                prompts = json.load(f)
        except Exception as e:
            console.print(f"[red]哎呀，加载提示词配置失败了: {e}[/red]")
            return 1
        
        # 显示菜单并获取用户选择
        commit_type = display_menu(prompts)
        
        # 如果是单文件分析模式
        if Path(config.project_path).is_file():
            console.print("[yellow]🔍 开始分析文件啦...[/yellow]")
            analyzer.analyze_file(config.project_path)
        else:
            console.print("[yellow]🔍 正在扫描项目目录...[/yellow]")
            analyzer.analyze_file(config.project_path)
        
        console.print("\n[green]🎨 正在生成分析报告...[/green]")
        analyzer.generate_report(commit_type=commit_type)
        console.print("\n[bold green]✨ 分析完成啦！快去看看报告吧~ ✨[/bold green]")
        
    except Exception as e:
        console.print(f"[red]抱歉，出了点小问题: {e}[/red]")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 