#!/usr/bin/env python3
"""
Frontend Project Dependency Analyzer
Analyzes frontend project dependencies and generates structured reports.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Union, DefaultDict, Tuple
from dataclasses import dataclass, field
from rich.console import Console
from rich.tree import Tree
from collections import defaultdict
import fnmatch
from functools import lru_cache
import hashlib

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

class DependencyMerkleTree:
    """依赖关系的Merkle树实现"""
    
    def __init__(self):
        self.nodes: Dict[str, MerkleNode] = {}
    
    def _calculate_hash(self, content: str) -> str:
        """计算内容的哈希值"""
        return hashlib.sha256(content.encode()).hexdigest()[:8]  # 使用短哈希以提高可读性
    
    def _create_node(self, name: str, type: str, content: Optional[str] = None) -> MerkleNode:
        """创建或获取节点"""
        if name in self.nodes:
            return self.nodes[name]
            
        node_content = content or name
        node_hash = self._calculate_hash(f"{type}:{node_content}")
        node = MerkleNode(hash=node_hash, type=type, name=name, content=content)
        self.nodes[name] = node
        return node
    
    def build_from_dependencies(self, deps: DependencyInfo, file_name: str) -> MerkleNode:
        """从依赖信息构建Merkle树"""
        root = self._create_node(file_name, 'file')
        
        # 添加组件依赖
        for comp_name in deps.components:
            comp_node = self._create_node(comp_name, 'component')
            root.children.append(comp_node)
        
        # 添加API依赖
        for api_name in deps.api:
            api_node = self._create_node(api_name, 'api')
            root.children.append(api_node)
        
        # 添加Hooks依赖
        for hook_name in deps.hooks:
            hook_node = self._create_node(hook_name, 'hook')
            root.children.append(hook_node)
        
        # 添加工具依赖
        for util_name in deps.utils:
            util_node = self._create_node(util_name, 'util')
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
        
        # 添加节点信息
        node_info = f"{prefix}[{root.type}:{root.hash}] {root.name}"
        result.append(node_info)
        
        # 递归处理子节点
        for child in root.children:
            result.append(self.generate_ai_readable_format(child, indent + 1))
        
        return "\n".join(result)

class FrontendAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        self.files: Dict[str, FileInfo] = {}
        self.dependency_graph: DefaultDict[str, Set[str]] = defaultdict(set)
        self.console = Console()
        self.search_index = SearchIndex()
        self.merkle_tree = DependencyMerkleTree()
        
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

    def _should_ignore(self, path: Path) -> bool:
        """Check if the file should be ignored"""
        return any(part in self.config.ignore_patterns for part in path.parts)

    def _determine_file_type(self, file_path: Path) -> Optional[str]:
        """Determine the type of the file based on its path and extension"""
        suffix = file_path.suffix
        
        # 从配置中获取文件类型
        for lang, lang_config in self.config.index_extensions.items():
            if suffix in lang_config['extensions']:
                return lang
                
        return None

    def _extract_dependencies(self, content: str, deps: DependencyInfo):
        """Extract all dependencies from file content"""
        for pattern_name, pattern in self.import_patterns.items():
            matches = re.finditer(pattern, content)
            for match in matches:
                import_path = match.group(1)
                self._categorize_dependency(import_path, deps)

    def _categorize_dependency(self, import_path: str, deps: DependencyInfo):
        """Categorize a dependency based on its import path"""
        # Handle absolute imports with @ alias
        if import_path.startswith('@/'):
            parts = import_path.split('/')
            if len(parts) > 1:
                category = parts[1]  # Get the category after @/
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
                    # Add to utils by default for other internal modules
                    deps.utils.add(import_path)
            return

        # Handle relative imports and other cases
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
            # Add to utils by default for other internal modules
            deps.utils.add(import_path)

    def _build_search_index(self):
        """构建文件搜索索引"""
        project_root = self.config.project_path.parent.parent.parent
        self.console.print("[yellow]Building search index...[/yellow]")
        
        # 获取所有支持的扩展名
        supported_extensions = set()
        if hasattr(self.config, 'index_extensions'):
            for lang_config in self.config.index_extensions.values():
                supported_extensions.update(lang_config['extensions'])
        
        for file_path in project_root.rglob('*'):
            if not file_path.is_file() or self._should_ignore(file_path):
                continue
                
            try:
                relative_path = str(file_path.relative_to(project_root))
                
                # 索引文件名
                self.search_index.file_index[file_path.name].add(relative_path)
                
                # 索引扩展名
                if file_path.suffix in supported_extensions:
                    self.search_index.extension_index[file_path.suffix].add(relative_path)
                    
                    # 只为特定扩展名的文件建立导入索引
                    content = file_path.read_text(encoding='utf-8')
                    
                    # 根据文件扩展名选择对应的导入模式
                    current_patterns = []
                    if hasattr(self.config, 'index_extensions'):
                        for lang_config in self.config.index_extensions.values():
                            if file_path.suffix in lang_config['extensions']:
                                current_patterns.extend(lang_config['patterns'])
                    else:
                        current_patterns = list(self.import_patterns.values())
                    
                    for pattern in current_patterns:
                        for match in re.finditer(pattern, content):
                            import_path = match.group(1)
                            # 添加原始导入路径
                            self.search_index.import_index[import_path].add(relative_path)
                            
                            # 处理相对路径，添加额外的索引项
                            if import_path.startswith('./') or import_path.startswith('../'):
                                file_dir = file_path.parent
                                try:
                                    resolved_path = (file_dir / import_path).resolve()
                                    if resolved_path.exists():
                                        rel_resolved = str(resolved_path.relative_to(project_root))
                                        self.search_index.import_index[rel_resolved].add(relative_path)
                                except:
                                    pass
                            
                            # 处理别名路径，添加额外的索引项
                            if import_path.startswith('@'):
                                for alias, path in self.config.alias_mappings.items():
                                    if import_path.startswith(alias):
                                        normalized_path = import_path.replace(alias, path, 1)
                                        self.search_index.import_index[normalized_path].add(relative_path)
                                        break
                            
            except Exception as e:
                self.console.print(f"[red]Error indexing {file_path}: {e}[/red]")

    @lru_cache(maxsize=1000)
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

    def _resolve_dependency_path(self, import_path: str) -> Optional[Path]:
        """解析依赖路径"""
        project_root = self.config.project_path.parent.parent.parent
        current_dir = self.config.project_path.parent
        
        # 1. 处理相对路径
        if import_path.startswith('./') or import_path.startswith('../'):
            # 从当前目录开始解析相对路径
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

    def _process_file(self, file_path: Path, depth: int = 0):
        """Process a single file and extract its dependencies"""
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
        """Analyze a specific file and its dependencies"""
        if depth > self.config.max_depth:
            return

        file_path = Path(file_path)
        if not file_path.exists():
            self.console.print(f"[red]Error: File {file_path} does not exist[/red]")
            return

        self.console.print(f"[green]Analyzing file: {file_path}[/green]")
        self._process_file(file_path, depth)
        
        if self.config.analyze_mode == "deep":
            self._analyze_dependencies(file_path, depth + 1)

    def _analyze_dependencies(self, file_path: Path, depth: int):
        """Recursively analyze dependencies of a file"""
        try:
            file_key = str(file_path.relative_to(self.config.project_path.parent.parent.parent))
        except ValueError:
            file_key = str(file_path)
            
        if file_key not in self.files:
            return

        file_info = self.files[file_key]
        deps = file_info.dependencies

        # Analyze component dependencies
        for comp_path, comp_dep in deps.components.items():
            resolved_path = self._resolve_dependency_path(comp_path)
            if resolved_path:
                self.dependency_graph[file_key].add(str(resolved_path))
                if not self._is_analyzed(resolved_path):
                    self.analyze_file(resolved_path, depth)

        # Analyze other dependencies (hooks, utils, etc.)
        for dep_set in [deps.hooks, deps.utils]:
            for dep_path in dep_set:
                resolved_path = self._resolve_dependency_path(dep_path)
                if resolved_path:
                    self.dependency_graph[file_key].add(str(resolved_path))
                    if not self._is_analyzed(resolved_path):
                        self.analyze_file(resolved_path, depth)

    def _is_analyzed(self, file_path: Path) -> bool:
        """Check if a file has already been analyzed"""
        try:
            relative_path = str(file_path.relative_to(self.config.project_path.parent.parent.parent))
            return relative_path in self.files and self.files[relative_path].analyzed
        except ValueError:
            return False

    def _find_circular_dependencies(self, start_file: str, path: List[str] = None) -> List[List[str]]:
        """Find circular dependencies starting from a file"""
        if path is None:
            path = []
        
        cycles = []
        current_path = path + [start_file]
        
        for dep in self.dependency_graph[start_file]:
            if dep in current_path:
                cycle_start = current_path.index(dep)
                cycles.append(current_path[cycle_start:] + [dep])
            else:
                cycles.extend(self._find_circular_dependencies(dep, current_path))
        
        return cycles

    def _format_dependency_path(self, original_path: str, resolved_path: Optional[Path]) -> str:
        """格式化依赖路径显示"""
        if not resolved_path:
            return original_path
        
        try:
            # 获取项目根目录
            project_root = self.config.project_path.parent.parent.parent
            
            # 如果是项目内的路径，转换为 @src 格式
            if str(resolved_path).startswith(str(project_root)):
                rel_path = resolved_path.relative_to(project_root)
                parts = rel_path.parts
                if parts and parts[0] == 'src':
                    return f"@{'/'.join(parts)}"
                return f"@/{'/'.join(parts)}"
            
            return original_path
        except:
            return original_path

    def generate_report(self):
        """生成并打印分析报告"""
        if not self.files:
            self.console.print("[yellow]未发现任何文件被分析。[/yellow]")
            return

        # 获取分析的文件
        try:
            target_file = Path(self.config.project_path)
            if target_file.is_file():
                rel_path = target_file.relative_to(target_file.parent.parent.parent)
                self.console.print(f"\n[bold cyan]═══════════════════════════════════════[/bold cyan]")
                self.console.print(f"[bold yellow]文件依赖分析报告[/bold yellow]")
                self.console.print(f"[bold cyan]═══════════════════════════════════════[/bold cyan]")
                self.console.print(f"\n[bold green]目标文件:[/bold green] @{rel_path}\n")

                # 生成Merkle树
                merkle_root = None
                for file_path, file_info in self.files.items():
                    if str(rel_path) in file_path:
                        merkle_root = self.merkle_tree.build_from_dependencies(file_info.dependencies, file_path)
                        break

                if merkle_root:
                    self.console.print("\n[bold yellow]AI快速阅读格式 (Merkle树)[/bold yellow]")
                    self.console.print("[cyan]" + "─" * 50 + "[/cyan]")
                    ai_readable = self.merkle_tree.generate_ai_readable_format(merkle_root)
                    self.console.print(ai_readable)
                    self.console.print("[cyan]" + "─" * 50 + "[/cyan]\n")

        except Exception as e:
            self.console.print(f"[red]错误: {e}[/red]")
            return

        def print_component_tree(deps: DependencyInfo, indent: int = 0, printed_components: Set[str] = None):
            """递归打印组件依赖树"""
            if printed_components is None:
                printed_components = set()
                
            for comp_path, comp_dep in deps.components.items():
                if comp_path in printed_components:
                    continue
                    
                prefix = "  " * indent + ("└── " if indent > 0 else "")
                self.console.print(f"{prefix}[green]{comp_path}[/green]")
                printed_components.add(comp_path)
                
                if comp_path in self.files:
                    nested_deps = self.files[comp_path].dependencies
                    print_component_tree(nested_deps, indent + 1, printed_components)

        # 处理每个文件的依赖
        for file_path, file_info in self.files.items():
            deps = file_info.dependencies
            
            # 打印分隔线
            self.console.print("\n[bold cyan]───────────────────────────────────[/bold cyan]")
            
            # 组件依赖
            if deps.components:
                self.console.print("\n[bold green]组件依赖[/bold green]")
                print_component_tree(deps)
            
            # API依赖
            if deps.api:
                self.console.print("\n[bold magenta]API 依赖[/bold magenta]")
                for api in sorted(deps.api):
                    self.console.print(f"  • {api}")
            
            # 类型依赖
            if deps.types:
                self.console.print("\n[bold blue]类型依赖[/bold blue]")
                for type_dep in sorted(deps.types):
                    self.console.print(f"  • {type_dep}")
            
            # Hooks依赖
            if deps.hooks:
                self.console.print("\n[bold yellow]Hooks 依赖[/bold yellow]")
                for hook in sorted(deps.hooks):
                    self.console.print(f"  • {hook}")
            
            # 工具依赖
            if deps.utils:
                self.console.print("\n[bold cyan]工具依赖[/bold cyan]")
                for util in sorted(deps.utils):
                    self.console.print(f"  • {util}")
            
            # 外部依赖
            if deps.external:
                self.console.print("\n[bold red]外部依赖[/bold red]")
                for ext in sorted(deps.external):
                    self.console.print(f"  • {ext}")

            # 循环依赖检查
            circular_deps = self._find_circular_dependencies(file_path)
            if circular_deps:
                self.console.print("\n[bold red]⚠️  循环依赖警告[/bold red]")
                for cycle in circular_deps:
                    self.console.print(f"  • {' → '.join(cycle)}")
            
            # 打印底部分隔线
            self.console.print("\n[bold cyan]═══════════════════════════════════════[/bold cyan]")

def main():
    """Main entry point"""
    console = Console()
    
    try:
        config = Config.load()
        analyzer = FrontendAnalyzer(config)
        
        # 初始化搜索索引
        analyzer._build_search_index()
        
        # 如果是单文件分析模式
        if Path(config.project_path).is_file():
            console.print("[yellow]Analyzing single file...[/yellow]")
            analyzer.analyze_file(config.project_path)
        else:
            console.print("[yellow]Scanning project directory...[/yellow]")
            analyzer.analyze_file(config.project_path)
        
        console.print("\n[green]Generating dependency report...[/green]")
        analyzer.generate_report()
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 