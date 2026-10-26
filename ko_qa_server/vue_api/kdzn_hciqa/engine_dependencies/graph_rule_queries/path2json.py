import json
from collections import defaultdict


def count_common_prefixes(lists):
    '''
    计算统一前缀长度
    '''
    if not lists:
        return 0

    # 找到最短列表的长度
    min_length = min(len(lst) for lst in lists)

    common_count = 0
    for i in range(min_length):
        # 获取所有列表的第i个元素
        elements = [lst[i] for lst in lists]
        # 检查所有元素是否相同
        if all(e == elements[0] for e in elements):
            common_count += 1
        else:
            break

    return common_count

def build_hierarchy_from_triplets(all_triplets):
    """
    从三元组构建层次化JSON结构
    """
    # 用于构建层次结构的字典
    hierarchy = defaultdict(lambda: defaultdict(lambda: defaultdict()))

    # 处理每个路径的三元组
    for triplets in all_triplets:
        # 从三元组中构建层次关系
        if len(triplets) >= 2:
            # 取前两个三元组来构建基本结构
            first_triplet = triplets[0]
            second_triplet = triplets[1]

            main_category = first_triplet[0]
            relation = first_triplet[1]
            sub_category = first_triplet[2]

            details = ""
            for idx, triplet in enumerate(triplets[2:]):
                if idx == 0:
                    details += f"{triplet[0]}-[{triplet[1]}]->{triplet[2]}"
                else:
                    details += f"-[{triplet[1]}]->{triplet[2]}"
            if details=="":
                details = second_triplet[2]
            if sub_category not in hierarchy[main_category][relation]:
                hierarchy[main_category][relation][sub_category] = {}
            if type(hierarchy[main_category][relation][sub_category]) is dict:
                if second_triplet[1] in hierarchy[main_category][relation][sub_category]:
                    hierarchy[main_category][relation][sub_category][second_triplet[1]].append(details)
                else:
                    hierarchy[main_category][relation][sub_category][second_triplet[1]] = [details]
        else:
            if "paths" not in hierarchy.keys():
                hierarchy["paths"][""][""] = []
            hierarchy["paths"][""][""].append(f"{triplets[0][0]}-{triplets[0][1]}->{triplets[0][2]}\n")
    # 转换为最终的JSON格式
    result = {}
    for main_cat, relations in hierarchy.items():
        result[main_cat] = []
        for relation, sub_categories in relations.items():
            relation_data = {relation: []}
            for sub_cat, methods in sub_categories.items():
                sub_cat_data = {sub_cat: methods}
                relation_data[relation].append(sub_cat_data)
            result[main_cat].append(relation_data)

    return result


def transform_paths_to_hierarchy(p2ts):
    """
    主函数：将路径列表转换为层次化结构
    (已修复 IndexError 和 数据冗余问题)
    """
    if not p2ts:
        return ""

    # --- 1. 数据去重 ---
    # 去除完全重复的路径，避免计算冗余和干扰前缀计算
    unique_p2ts = []
    seen = set()
    for p in p2ts:
        # 将 list of tuples 转为 tuple of tuples 以便哈希去重
        p_tuple = tuple(p)
        if p_tuple not in seen:
            seen.add(p_tuple)
            unique_p2ts.append(p)

    p2ts = unique_p2ts  # 更新为去重后的列表

    # --- 2. 计算公共前缀长度 ---
    if len(p2ts) == 0:
        return ""

    # 假设 count_common_prefixes 是你外部定义的函数，这里直接调用
    # 如果没有该函数，通常它的逻辑是比较所有路径的第i个元素是否相同
    try:
        prefix_len = count_common_prefixes(p2ts)
    except NameError:
        # 如果找不到这个函数，这里给一个简易实现兜底
        prefix_len = 0
        if p2ts and len(p2ts[0]) > 0:
            reference = p2ts[0]
            for i in range(len(reference)):
                current_node = reference[i]
                if all(len(p) > i and p[i] == current_node for p in p2ts):
                    prefix_len += 1
                else:
                    break

    # --- 3. ★关键修复：防止越界★ ---
    # 如果只有一条路径，或者公共前缀等于最短路径的长度，
    # 必须回退一步，否则 triplet[prefix_len] 会越界。
    # 我们至少需要保留最后一个三元组来显示具体的节点信息。
    min_path_len = min(len(p) for p in p2ts)

    # 如果前缀把整个路径都吞了，或者只剩0长度，强制减1
    if prefix_len >= min_path_len:
        prefix_len = max(0, min_path_len - 1)

    # 如果只有一条路径，通常保留倒数两跳或根据业务逻辑调整
    # 你原代码里的逻辑：prefix_len = max(len(p2ts[0])-2, 0)
    if len(p2ts) == 1:
        # 保持你原有的特定逻辑：单条路径时，前缀保留到倒数第2个
        prefix_len = max(len(p2ts[0]) - 2, 0)

    # --- 4. 构建前缀字符串 ---
    prefix = ""
    if prefix_len > 0:
        # 使用第一条路径来构建前缀字符串
        ref_path = p2ts[0]
        for i in range(prefix_len):
            if i == 0:
                # 只有第一个三元组需要包含头实体
                prefix += f"{ref_path[i][0]}-[{ref_path[i][1]}]->{ref_path[i][2]}"
            else:
                # 后续三元组只追加 关系->尾实体
                prefix += f"-[{ref_path[i][1]}]->{ref_path[i][2]}"

    # --- 5. 重组三元组 ---
    new_all_triplets = []

    # 只有当前缀不为空，且确实有公共部分时才进行压缩
    if prefix != "" and prefix_len > 0:
        for triplet in p2ts:
            # 安全检查：确保当前路径长度足够
            if len(triplet) > prefix_len:
                # 截取剩余部分
                remaining = triplet[prefix_len + 1:]

                # 构建新的起始三元组：(前缀字符串, 下一跳关系, 下一跳实体)
                # 这里的 triplet[prefix_len] 就是由于上面修复了越界问题，现在是安全的
                head_triplet = (prefix, triplet[prefix_len][1], triplet[prefix_len][2])

                new_triplet = [head_triplet] + remaining
                new_all_triplets.append(new_triplet)
            else:
                # 理论上不会走到这里，除非路径比前缀还短（已被min_path_len拦截）
                new_all_triplets.append(triplet)
    else:
        new_all_triplets = p2ts

    # --- 6. 构建JSON结构 ---
    # 假设 build_hierarchy_from_triplets 是你外部定义的函数
    try:
        result = build_hierarchy_from_triplets(new_all_triplets)
        json_txt = json.dumps(result, ensure_ascii=False, indent=2)
        return json_txt
    except Exception as e:
        print(f"JSON构建失败: {e}")
        return "[]"


# def transform_paths_to_hierarchy(p2ts):
#     """
#     主函数：将路径列表转换为层次化结构
#     """
#     if len(p2ts) == 0:
#         return ""
#     prefix_len = count_common_prefixes(p2ts)
#     if len(p2ts) ==  1:
#         prefix_len = max(len(p2ts[0])-2, 0)
#     prefix = ""
#     for i in range(prefix_len):
#         if i == 0:
#             prefix += p2ts[0][i][0] + "-" + p2ts[0][i][1] + "->" + p2ts[0][i][2]
#         else:
#             prefix += "-" + p2ts[0][i][1] + "->" + p2ts[0][i][2]
#     new_all_triplets = []
#     if prefix != "":
#         for triplet in p2ts:
#             remaining = triplet[prefix_len + 1:]
#             new_triplet = [(prefix, triplet[prefix_len][1], triplet[prefix_len][2])] + remaining
#             new_all_triplets.append(new_triplet)
#     else:
#         new_all_triplets = p2ts
#     # 3: 构建JSON结构
#     result = build_hierarchy_from_triplets(new_all_triplets)
#
#     json_txt = json.dumps(result, ensure_ascii=False, indent=2)
#
#     return json_txt


def _is_chainable_path(path):
    """判断一条路径是否可串联：每跳的 tail == 下一跳的 head"""
    if not path or len(path) == 1:
        return True
    return all(path[i][2] == path[i+1][0] for i in range(len(path)-1))


def transform_paths_to_hierarchy_jiapu(p2ts):
    """
    主函数：将路径列表转换为层次化结构（最小改动版）
    - 并列事实：自动拆成单跳路径，避免人物丢失
    - 可串联路径：继续保留你的“公共前缀折叠”，但不再用字符串替换 head
    """
    if len(p2ts) == 0:
        return ""

    # NEW(1): 先兜底处理“并列事实”（不连通的路径）——拆成单跳路径
    if any(not _is_chainable_path(p) for p in p2ts):
        p2ts = [[tri] for path in p2ts for tri in path]

    prefix_len = count_common_prefixes(p2ts)
    if len(p2ts) ==  1:
        prefix_len = max(len(p2ts[0])-2, 0)

    # CHG(2): 不再拼“prefix”字符串、更不再用它去替换 head
    new_all_triplets = p2ts
    if prefix_len > 0:
        # 仅当后缀真的从“公共前缀最后一跳的 tail”继续时才压缩；否则保持原样
        expected_head = p2ts[0][prefix_len - 1][2]
        tmp = []
        ok = True

        # 是否存在需要压缩的后缀
        any_suffix = any(len(p) > prefix_len for p in p2ts)

        if any_suffix:
            for path in p2ts:
                if len(path) == prefix_len:
                    # 刚好等于公共前缀——用空后缀占位（你的 build_hierarchy_* 若不支持空可在此放弃压缩）
                    tmp.append([])
                else:
                    # 必须从 expected_head 接着走
                    if path[prefix_len][0] != expected_head:
                        ok = False
                        break
                    tmp.append(path[prefix_len:])
        else:
            # 全部都等于公共前缀——压缩成空后缀集合（如不支持空，也可直接 ok=False）
            tmp = [[] for _ in p2ts]

        if ok:
            new_all_triplets = tmp
        # 若不 ok，则保持 new_all_triplets = p2ts（不做压缩）

    # 3: 构建JSON结构（保持你原来的调用）
    result = build_hierarchy_from_triplets(new_all_triplets)
    json_txt = json.dumps(result, ensure_ascii=False, indent=2)
    return json_txt


if __name__ == '__main__':
    # 示例输入数据
    input_paths = [[('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油箱磁屏蔽接地不良'), ('油箱磁屏蔽接地不良', '检查方法或部位', '测量绝缘电阻'), ('测量绝缘电阻', '要求', '打开所有磁屏蔽接地点，对磁屏蔽进行绝缘电阻测量')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油箱磁屏蔽接地不良'), ('油箱磁屏蔽接地不良', '检查方法或部位', '目测'), ('目测', '要求', '磁屏蔽松动或有放电形成的游离碳')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油箱磁屏蔽接地不良'), ('油箱磁屏蔽接地不良', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '以C2H2为主，且通常伴有C2H4、CH4等')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '绕组或引线绝缘击穿'), ('绕组或引线绝缘击穿', '检查方法或部位', '目测'), ('目测', '要求', 'a）观测气体继电器内的气体，并取气样色谱分析，这时主要气体是H2和C2H2; b）结合吊罩（心）或进油箱内部，重点检查绝缘件表面和分接开关触头间有无放电痕迹，如有应查明原因，并予以更换处理')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '绕组或引线绝缘击穿'), ('绕组或引线绝缘击穿', '检查方法或部位', '油中金属微量测试'), ('油中金属微量测试', '要求', '测试结果若存在金属铜含量较大，表明绕组已烧损')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '绕组或引线绝缘击穿'), ('绕组或引线绝缘击穿', '检查方法或部位', '局部放电量测试'), ('局部放电量测试', '要求', '可结合局放定位进行局部放电量测试，以查明放电部位及可能产生的原因')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '绕组或引线绝缘击穿'), ('绕组或引线绝缘击穿', '检查方法或部位', '绝缘电阻测试'), ('绝缘电阻测试', '要求', '如内部存在对地树枝状的放电，绝缘电阻会有下降的可能，故检测绝缘电阻，可判断放电的程度')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '绕组或引线绝缘击穿'), ('绕组或引线绝缘击穿', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', 'a）具有高能量电弧放电特征，主要气体是 H2 和C2H2: b）涉及固体绝缘材料，会产生CO 和 CO2气体')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '气泡放电'), ('气泡放电', '检查方法或部位', '残气检查'), ('残气检查', '要求', 'a）检查各放气塞是否有剩余气体放出； b）在储油柜上抽微真空，检查其气体继电器内是否有气泡通过')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '气泡放电'), ('气泡放电', '检查方法或部位', '油中含气量测试'), ('油中含气量测试', '要求', 'a）如油中含气量过大，并有增长的趋势，应重点检查储油柜、油箱、油泵和在线油色谱装置等是否有渗漏； b）油中含气量接近饱和值时，环境温度或负荷变化较大后，会在油中产生气泡')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '气泡放电'), ('气泡放电', '检查方法或部位', '目测和气样分析'), ('目测和气样分析', '要求', '检查气体继电器内的气体，取气样分析，如主要是O2和N2，表明是气泡放电')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '气泡放电'), ('气泡放电', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '具有低能量局部放电，产生主要气体是H2和CH4')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '金属尖端放电'), ('金属尖端放电', '检查方法或部位', '目测'), ('目测', '要求', '重点检查铁心和金属尖角有无放电痕迹')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '金属尖端放电'), ('金属尖端放电', '检查方法或部位', '局部放电量测试'), ('局部放电量测试', '要求', '可结合局放定位进行局部放电量测试，以查明放电部位及可能产生的原因')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '金属尖端放电'), ('金属尖端放电', '检查方法或部位', '油中金属微量测试'), ('油中金属微量测试', '要求', 'a）若铁含量较高，表明铁心或结构件放电； b）若铜含量较高，表明绕组或引线放电')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '金属尖端放电'), ('金属尖端放电', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '油色谱中特征气体增长')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '不稳定的铁心多点接地'), ('不稳定的铁心多点接地', '检查方法或部位', '运行中测量铁心接地电流'), ('运行中测量铁心接地电流', '要求', '接地电流时大时小，可采取加限流电阻办法限制，或适时按上述办法停电处理')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '不稳定的铁心多点接地'), ('不稳定的铁心多点接地', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '属低能量火花放电，并有局部过热特征，这时伴随少量H2和C2H2产生')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '导电回路接触不良及其分流'), ('导电回路接触不良及其分流', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '油中溶解气体分析属低能量火花放电，并有局部过热特征，这时伴随少量C2H2产生')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '导电回路接触不良及其分流'), ('导电回路接触不良及其分流', '检查方法或部位', '油中金属微量测试'), ('油中金属微量测试', '要求', '测试结果若金属铜含量较大，表明导电回路存在放电现象')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '有载分接开关绝缘筒渗漏'), ('有载分接开关绝缘筒渗漏', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '油中溶解气体分析属高能量放电，并有局部过热特征')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油流带电'), ('油流带电', '检查方法或部位', '泄漏电流或静电感应电压测量'), ('泄漏电流或静电感应电压测量', '要求', '开启油泵，测量中性点的静电感应电压或泄漏电流，如长时间不稳定或稳定值超出规定值，则表明可能发生了油流带电现象')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油流带电'), ('油流带电', '检查方法或部位', '油中带电度测试'), ('油中带电度测试', '要求', '测量油中带电度，如超出规定值，内部可能存在油流带电、放电现象')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油流带电'), ('油流带电', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '油色谱特征气体增长')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '悬浮电位放电'), ('悬浮电位放电', '检查方法或部位', '局部放电量测试'), ('局部放电量测试', '要求', '可结合局放定位进行局部放电量测试，以查明放电部位及可能产生的原因')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '悬浮电位放电'), ('悬浮电位放电', '检查方法或部位', '目测'), ('目测', '要求', 'a）所有等电位的连接是否良好； b）逐一检查结构件或电、磁屏蔽等有无短路、变色、过热现象')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '悬浮电位放电'), ('悬浮电位放电', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', '具有低能量放电特征')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '悬浮杂质放电'), ('悬浮杂质放电', '检查方法或部位', '油颗粒度测试'), ('油颗粒度测试', '要求', '油颗粒度较大或较多，并含有金属成分')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '悬浮杂质放电'), ('悬浮杂质放电', '检查方法或部位', '油中含气量测试'), ('油中含气量测试', '要求', '属低能量局部放电，时有时无，这时产生的主要气体是 H2和 CH4')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油泵内部放电'), ('油泵内部放电', '检查方法或部位', '解体检查'), ('解体检查', '要求', 'a）定子绕组绝缘状态，在铁心、绕组表面上有无放电痕迹; b）轴承磨损情况，或转子和定子之间是否有金属异物引起的高温磨擦')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油泵内部放电'), ('油泵内部放电', '检查方法或部位', '绕组绝缘电阻测试'), ('绕组绝缘电阻测试', '要求', '采用500V或1000V绝缘电阻表测量对地绝缘电阻值，应大于1MΩ')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油泵内部放电'), ('油泵内部放电', '检查方法或部位', '油泵运行检查'), ('油泵运行检查', '要求', '油泵内部存在局部放电，可能是定子绕组的绝缘不良引起的放电')], [('电力变压器', 'HAS_INSPECTION', '检查'), ('检查', '类型', '放电性异常检查'), ('放电性异常检查', '可能的异常原因', '油泵内部放电'), ('油泵内部放电', '检查方法或部位', '油中溶解气体分析'), ('油中溶解气体分析', '要求', 'a）属高能量局部放电，这时产生的主要气体是H2和 C2H2; b）若伴有局部过热特征则是摩擦引起的高温')]]

    # 执行转换
    hierarchy_json = transform_paths_to_hierarchy(input_paths)

    # 输出结果（美化格式）
    print(hierarchy_json)